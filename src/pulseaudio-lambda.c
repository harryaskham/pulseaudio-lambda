/***
  PulseAudio Lambda Bridge
  
  This program creates a bridge that captures audio from a PulseAudio source,
  pipes it through an external process (lambda) via stdin/stdout, and plays
  the result to a PulseAudio sink.
***/

#define _POSIX_C_SOURCE 200112L
#define _DEFAULT_SOURCE  // For usleep on some systems

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>

#include <pulse/pulseaudio.h>
#include <pulse/simple.h>

#define DEFAULT_SAMPLE_RATE 44100
#define DEFAULT_CHANNELS 2
#define DEFAULT_BUFFER_SIZE 1024

typedef struct {
    char *source_name;
    char *sink_name;
    char *lambda_command;
    
    // Audio format parameters
    uint32_t sample_rate;
    uint8_t channels;
    uint32_t buffer_size;
    
    pa_simple *source_conn;
    pa_simple *sink_conn;
    
    pid_t lambda_pid;
    int pipe_to_lambda[2];
    int pipe_from_lambda[2];
    
    int running;
} lambda_bridge_t;

static lambda_bridge_t bridge = {0};

static void cleanup(void) {
    printf("Cleaning up...\n");
    
    bridge.running = 0;
    
    if (bridge.source_conn) {
        pa_simple_free(bridge.source_conn);
        bridge.source_conn = NULL;
    }
    
    if (bridge.sink_conn) {
        pa_simple_free(bridge.sink_conn);
        bridge.sink_conn = NULL;
    }
    
    if (bridge.lambda_pid > 0) {
        kill(bridge.lambda_pid, SIGTERM);
        waitpid(bridge.lambda_pid, NULL, 0);
        bridge.lambda_pid = 0;
    }
    
    if (bridge.pipe_to_lambda[0] >= 0) close(bridge.pipe_to_lambda[0]);
    if (bridge.pipe_to_lambda[1] >= 0) close(bridge.pipe_to_lambda[1]);
    if (bridge.pipe_from_lambda[0] >= 0) close(bridge.pipe_from_lambda[0]);
    if (bridge.pipe_from_lambda[1] >= 0) close(bridge.pipe_from_lambda[1]);
}

static void signal_handler(int sig) {
    printf("Received signal %d, shutting down\n", sig);
    cleanup();
    exit(0);
}

static int spawn_lambda(void) {
    if (pipe(bridge.pipe_to_lambda) < 0) {
        fprintf(stderr, "Failed to create pipe to lambda: %s\n", strerror(errno));
        return -1;
    }
    
    if (pipe(bridge.pipe_from_lambda) < 0) {
        fprintf(stderr, "Failed to create pipe from lambda: %s\n", strerror(errno));
        return -1;
    }
    
    bridge.lambda_pid = fork();
    
    if (bridge.lambda_pid < 0) {
        fprintf(stderr, "Failed to fork lambda process: %s\n", strerror(errno));
        return -1;
    }
    
    if (bridge.lambda_pid == 0) {
        // Child process - setup lambda
        close(bridge.pipe_to_lambda[1]);
        close(bridge.pipe_from_lambda[0]);
        
        if (dup2(bridge.pipe_to_lambda[0], STDIN_FILENO) < 0) {
            perror("dup2 stdin");
            _exit(1);
        }
        
        if (dup2(bridge.pipe_from_lambda[1], STDOUT_FILENO) < 0) {
            perror("dup2 stdout");
            _exit(1);
        }
        
        close(bridge.pipe_to_lambda[0]);
        close(bridge.pipe_from_lambda[1]);
        
        // Set up environment variables for lambda
        char sample_rate_str[32];
        char channels_str[32]; 
        char buffer_size_str[32];
        char bytes_per_sample_str[32];
        char bytes_per_frame_str[32];
        char bits_str[32];
        
        snprintf(sample_rate_str, sizeof(sample_rate_str), "%u", bridge.sample_rate);
        snprintf(channels_str, sizeof(channels_str), "%u", bridge.channels);
        snprintf(buffer_size_str, sizeof(buffer_size_str), "%u", bridge.buffer_size);
        snprintf(bytes_per_sample_str, sizeof(bytes_per_sample_str), "2"); // S16LE = 2 bytes
        snprintf(bytes_per_frame_str, sizeof(bytes_per_frame_str), "%u", bridge.channels * 2);
        snprintf(bits_str, sizeof(bits_str), "16"); // S16LE = 16 bits
        
        setenv("PA_LAMBDA_SAMPLE_RATE", sample_rate_str, 1);
        setenv("PA_LAMBDA_CHANNELS", channels_str, 1);
        setenv("PA_LAMBDA_BUFFER_SIZE", buffer_size_str, 1);
        setenv("PA_LAMBDA_SAMPLE_FORMAT", "s16le", 1);
        setenv("PA_LAMBDA_BYTES_PER_SAMPLE", bytes_per_sample_str, 1);
        setenv("PA_LAMBDA_BYTES_PER_FRAME", bytes_per_frame_str, 1);
        setenv("PA_LAMBDA_SIGNED", "signed", 1);
        setenv("PA_LAMBDA_BITS", bits_str, 1);
        
        execl("/bin/sh", "sh", "-c", bridge.lambda_command, NULL);
        perror("execl");
        _exit(1);
    }
    
    // Parent process
    close(bridge.pipe_to_lambda[0]);
    close(bridge.pipe_from_lambda[1]);
    
    // Make pipes non-blocking
    int flags;
    flags = fcntl(bridge.pipe_to_lambda[1], F_GETFL);
    fcntl(bridge.pipe_to_lambda[1], F_SETFL, flags | O_NONBLOCK);
    
    flags = fcntl(bridge.pipe_from_lambda[0], F_GETFL);
    fcntl(bridge.pipe_from_lambda[0], F_SETFL, flags | O_NONBLOCK);
    
    printf("Lambda process spawned with PID %d\n", bridge.lambda_pid);
    return 0;
}

static int init_pulseaudio(void) {
    pa_sample_spec sample_spec = {
        .format = PA_SAMPLE_S16LE,
        .rate = bridge.sample_rate,
        .channels = bridge.channels
    };
    
    pa_buffer_attr buffer_attr = {
        .maxlength = (uint32_t) -1,
        .tlength = bridge.buffer_size * sizeof(int16_t) * bridge.channels,
        .prebuf = (uint32_t) -1,
        .minreq = (uint32_t) -1,
        .fragsize = bridge.buffer_size * sizeof(int16_t) * bridge.channels
    };
    
    int error;
    
    // Connect to source (for recording)
    bridge.source_conn = pa_simple_new(
        NULL,                    // server
        "pulseaudio-lambda",     // application name
        PA_STREAM_RECORD,        // direction
        bridge.source_name,      // device name
        "Lambda Input",          // stream description
        &sample_spec,           // sample format
        NULL,                   // channel map
        &buffer_attr,           // buffering attributes
        &error
    );
    
    if (!bridge.source_conn) {
        fprintf(stderr, "Failed to connect to source '%s': %s\n", 
                bridge.source_name ? bridge.source_name : "default",
                pa_strerror(error));
        return -1;
    }
    
    // Connect to sink (for playback)
    bridge.sink_conn = pa_simple_new(
        NULL,                    // server
        "pulseaudio-lambda",     // application name  
        PA_STREAM_PLAYBACK,      // direction
        bridge.sink_name,        // device name
        "Lambda Output",         // stream description
        &sample_spec,           // sample format
        NULL,                   // channel map
        &buffer_attr,           // buffering attributes
        &error
    );
    
    if (!bridge.sink_conn) {
        fprintf(stderr, "Failed to connect to sink '%s': %s\n",
                bridge.sink_name ? bridge.sink_name : "default", 
                pa_strerror(error));
        return -1;
    }
    
    printf("Connected to PulseAudio:\n");
    printf("  Source: %s\n", bridge.source_name ? bridge.source_name : "default");
    printf("  Sink: %s\n", bridge.sink_name ? bridge.sink_name : "default");
    
    return 0;
}

static void run_bridge(void) {
    size_t buffer_bytes = bridge.buffer_size * sizeof(int16_t) * bridge.channels;
    uint8_t *buffer = malloc(buffer_bytes);
    if (!buffer) {
        fprintf(stderr, "Failed to allocate audio buffer\n");
        return;
    }
    int error;
    
    bridge.running = 1;
    printf("Bridge running - press Ctrl+C to stop\n");
    printf("Buffer size: %zu bytes per cycle\n", buffer_bytes);
    
    while (bridge.running) {
        // Read from PulseAudio source
        if (pa_simple_read(bridge.source_conn, buffer, buffer_bytes, &error) < 0) {
            fprintf(stderr, "Failed to read from source: %s\n", pa_strerror(error));
            break;
        }
        
        // Send to lambda process (non-blocking)
        ssize_t written = 0;
        size_t total_written = 0;
        while (total_written < buffer_bytes) {
            written = write(bridge.pipe_to_lambda[1], buffer + total_written, buffer_bytes - total_written);
            if (written < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    usleep(100); // Brief pause before retrying
                    continue;
                } else {
                    perror("Failed to write to lambda");
                    break;
                }
            }
            total_written += written;
        }
        
        if (total_written != buffer_bytes) {
            fprintf(stderr, "Failed to write complete buffer to lambda\n");
            break;
        }
        
        // Try to read from lambda process (non-blocking)
        // Note: We may not get data immediately if lambda is buffering
        ssize_t bytes_read = read(bridge.pipe_from_lambda[0], buffer, buffer_bytes);
        
        if (bytes_read < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                // No data available yet - this is normal for buffering lambdas
                // Skip this iteration and continue
                continue;
            } else {
                perror("Failed to read from lambda");
                break;
            }
        } else if (bytes_read == 0) {
            printf("Lambda process ended\n");
            break;
        }
        
        // Write to PulseAudio sink (only if we got data)
        if (bytes_read > 0) {
            if (pa_simple_write(bridge.sink_conn, buffer, bytes_read, &error) < 0) {
                fprintf(stderr, "Failed to write to sink: %s\n", pa_strerror(error));
                break;
            }
        }
    }
    
    free(buffer);
}

static void print_usage(const char *prog) {
    printf("Usage: %s [options] <lambda_command>\n", prog);
    printf("Options:\n");
    printf("  -s, --source=NAME    PulseAudio source name\n");
    printf("  -o, --sink=NAME      PulseAudio sink name  \n");
    printf("  -h, --help           Show this help\n");
    printf("\nExample:\n");
    printf("  %s -s alsa_input.pci-0000_00_1f.3.analog-stereo \\\n", prog);
    printf("         -o alsa_output.pci-0000_00_1f.3.analog-stereo \\\n");
    printf("         './lambdas/identity.sh'\n");
    printf("\n");
    printf("  # Or use default devices:\n");
    printf("  %s './lambdas/identity.sh'\n", prog);
}

int main(int argc, char *argv[]) {
    // Initialize pipe file descriptors
    bridge.pipe_to_lambda[0] = bridge.pipe_to_lambda[1] = -1;
    bridge.pipe_from_lambda[0] = bridge.pipe_from_lambda[1] = -1;
    
    // Initialize audio format parameters
    bridge.sample_rate = DEFAULT_SAMPLE_RATE;
    bridge.channels = DEFAULT_CHANNELS;
    bridge.buffer_size = DEFAULT_BUFFER_SIZE;
    
    // Parse command line arguments
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (strncmp(argv[i], "-s=", 3) == 0 || strncmp(argv[i], "--source=", 9) == 0) {
            bridge.source_name = strchr(argv[i], '=') + 1;
        } else if (strncmp(argv[i], "-o=", 3) == 0 || strncmp(argv[i], "--sink=", 7) == 0) {
            bridge.sink_name = strchr(argv[i], '=') + 1;
        } else if (argv[i][0] != '-') {
            bridge.lambda_command = argv[i];
            break;
        }
    }
    
    if (!bridge.lambda_command) {
        fprintf(stderr, "Error: Lambda command is required\n");
        print_usage(argv[0]);
        return 1;
    }
    
    // Setup signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    atexit(cleanup);
    
    printf("PulseAudio Lambda Bridge\n");
    printf("Lambda: %s\n", bridge.lambda_command);
    printf("Audio Format: %s, %uHz, %u channels, %u samples buffer\n",
           "S16LE", bridge.sample_rate, bridge.channels, bridge.buffer_size);
    
    // Initialize components
    if (spawn_lambda() < 0) {
        return 1;
    }
    
    if (init_pulseaudio() < 0) {
        return 1;
    }
    
    // Run the bridge
    run_bridge();
    
    return 0;
}