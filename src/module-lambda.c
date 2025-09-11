/***
  PulseAudio Lambda Module
  
  This module creates a sink and source that pipes audio through an external
  process (lambda) via stdin/stdout for processing.
***/

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>

#include <pulse/xmalloc.h>
#include <pulse/timeval.h>
#include <pulse/rtclock.h>

#include <pulsecore/core.h>
#include <pulsecore/module.h>
#include <pulsecore/core-util.h>
#include <pulsecore/modargs.h>
#include <pulsecore/log.h>
#include <pulsecore/sink.h>
#include <pulsecore/source.h>
#include <pulsecore/thread.h>
#include <pulsecore/thread-mq.h>
#include <pulsecore/rtpoll.h>
#include <pulsecore/poll.h>

PA_MODULE_AUTHOR("PulseAudio Lambda Contributors");
PA_MODULE_DESCRIPTION("Route audio through external process via stdin/stdout");
PA_MODULE_VERSION(PACKAGE_VERSION);
PA_MODULE_LOAD_ONCE(false);
PA_MODULE_USAGE(
    "sink_name=<name of the sink> "
    "source_name=<name of the source> "
    "lambda_command=<command to execute> "
    "format=<sample format> "
    "rate=<sample rate> "
    "channels=<number of channels> "
    "channel_map=<channel map>");

#define DEFAULT_SINK_NAME "lambda_sink"
#define DEFAULT_SOURCE_NAME "lambda_source"
#define PIPE_BUF_SIZE (1024 * 16)

static const char* const valid_modargs[] = {
    "sink_name",
    "source_name", 
    "lambda_command",
    "format",
    "rate",
    "channels",
    "channel_map",
    NULL
};

struct userdata {
    pa_core *core;
    pa_module *module;
    
    pa_sink *sink;
    pa_source *source;
    
    pa_thread *thread;
    pa_thread_mq thread_mq;
    pa_rtpoll *rtpoll;
    
    char *lambda_command;
    pid_t lambda_pid;
    int pipe_to_lambda;
    int pipe_from_lambda;
    
    pa_memchunk memchunk;
    
    pa_rtpoll_item *rtpoll_item_read;
    pa_rtpoll_item *rtpoll_item_write;
};

static void thread_func(void *userdata) {
    struct userdata *u = userdata;
    
    pa_assert(u);
    
    pa_log_debug("Thread starting up");
    
    pa_thread_mq_install(&u->thread_mq);
    
    for (;;) {
        int ret;
        struct pollfd *pollfd;
        
        pollfd = pa_rtpoll_item_get_pollfd(u->rtpoll_item_read, NULL);
        
        if ((ret = pa_rtpoll_run(u->rtpoll)) < 0)
            goto fail;
        
        if (ret == 0)
            goto finish;
        
        if (pollfd && (pollfd->revents & POLLIN)) {
            ssize_t l;
            void *p;
            
            if (!u->memchunk.memblock) {
                u->memchunk.memblock = pa_memblock_new(u->core->mempool, PIPE_BUF_SIZE);
                u->memchunk.index = u->memchunk.length = 0;
            }
            
            pa_assert(pa_memblock_get_length(u->memchunk.memblock) > u->memchunk.index);
            
            p = pa_memblock_acquire(u->memchunk.memblock);
            l = pa_read(u->pipe_from_lambda, 
                       (uint8_t*) p + u->memchunk.index,
                       pa_memblock_get_length(u->memchunk.memblock) - u->memchunk.index,
                       NULL);
            pa_memblock_release(u->memchunk.memblock);
            
            pa_assert(l != 0);
            
            if (l < 0) {
                if (errno == EINTR)
                    continue;
                else if (errno != EAGAIN) {
                    pa_log("Failed to read from pipe: %s", pa_cstrerror(errno));
                    goto fail;
                }
            } else {
                u->memchunk.length = (size_t) l;
                pa_source_post(u->source, &u->memchunk);
                u->memchunk.index += (size_t) l;
                
                if (u->memchunk.index >= pa_memblock_get_length(u->memchunk.memblock)) {
                    pa_memblock_unref(u->memchunk.memblock);
                    pa_memchunk_reset(&u->memchunk);
                }
            }
        }
    }
    
fail:
    pa_asyncmsgq_post(u->thread_mq.outq, PA_MSGOBJECT(u->core), PA_CORE_MESSAGE_UNLOAD_MODULE, u->module, 0, NULL, NULL);
    pa_asyncmsgq_wait_for(u->thread_mq.inq, PA_MESSAGE_SHUTDOWN);
    
finish:
    pa_log_debug("Thread shutting down");
}

static int sink_process_msg(pa_msgobject *o, int code, void *data, int64_t offset, pa_memchunk *chunk) {
    struct userdata *u = PA_SINK(o)->userdata;
    
    switch (code) {
        case PA_SINK_MESSAGE_GET_LATENCY:
            *((pa_usec_t*) data) = 0;
            return 0;
            
        case PA_SINK_MESSAGE_ADD_INPUT:
        case PA_SINK_MESSAGE_REMOVE_INPUT:
            return 0;
    }
    
    return pa_sink_process_msg(o, code, data, offset, chunk);
}

static int source_process_msg(pa_msgobject *o, int code, void *data, int64_t offset, pa_memchunk *chunk) {
    struct userdata *u = PA_SOURCE(o)->userdata;
    
    switch (code) {
        case PA_SOURCE_MESSAGE_GET_LATENCY:
            *((pa_usec_t*) data) = 0;
            return 0;
            
        case PA_SOURCE_MESSAGE_ADD_OUTPUT:
        case PA_SOURCE_MESSAGE_REMOVE_OUTPUT:
            return 0;
    }
    
    return pa_source_process_msg(o, code, data, offset, chunk);
}

static void sink_request_cb(pa_sink *s) {
    struct userdata *u;
    pa_sink_assert_ref(s);
    pa_assert_se(u = s->userdata);
    
    pa_memchunk chunk;
    pa_sink_render(s, PIPE_BUF_SIZE, &chunk);
    
    if (chunk.memblock) {
        const void *p;
        p = pa_memblock_acquire(chunk.memblock);
        pa_write(u->pipe_to_lambda, (const uint8_t*) p + chunk.index, chunk.length, NULL);
        pa_memblock_release(chunk.memblock);
        pa_memblock_unref(chunk.memblock);
    }
}

static void sink_update_requested_latency_cb(pa_sink *s) {
    struct userdata *u;
    pa_sink_assert_ref(s);
    pa_assert_se(u = s->userdata);
    
    pa_sink_set_max_request(s, pa_sink_get_requested_latency(s));
}

static void source_update_requested_latency_cb(pa_source *s) {
    struct userdata *u;
    pa_source_assert_ref(s);
    pa_assert_se(u = s->userdata);
}

static int spawn_lambda(struct userdata *u) {
    int pipe_stdin[2], pipe_stdout[2];
    
    pa_assert(u);
    pa_assert(u->lambda_command);
    
    if (pipe(pipe_stdin) < 0 || pipe(pipe_stdout) < 0) {
        pa_log("pipe() failed: %s", pa_cstrerror(errno));
        return -1;
    }
    
    u->lambda_pid = fork();
    
    if (u->lambda_pid < 0) {
        pa_log("fork() failed: %s", pa_cstrerror(errno));
        close(pipe_stdin[0]);
        close(pipe_stdin[1]);
        close(pipe_stdout[0]);
        close(pipe_stdout[1]);
        return -1;
    }
    
    if (u->lambda_pid == 0) {
        close(pipe_stdin[1]);
        close(pipe_stdout[0]);
        
        if (dup2(pipe_stdin[0], STDIN_FILENO) < 0) {
            _exit(1);
        }
        if (dup2(pipe_stdout[1], STDOUT_FILENO) < 0) {
            _exit(1);
        }
        
        close(pipe_stdin[0]);
        close(pipe_stdout[1]);
        
        execl("/bin/sh", "sh", "-c", u->lambda_command, NULL);
        _exit(1);
    }
    
    close(pipe_stdin[0]);
    close(pipe_stdout[1]);
    
    u->pipe_to_lambda = pipe_stdin[1];
    u->pipe_from_lambda = pipe_stdout[0];
    
    pa_make_fd_nonblock(u->pipe_to_lambda);
    pa_make_fd_nonblock(u->pipe_from_lambda);
    
    pa_log_info("Lambda process spawned with PID %d", u->lambda_pid);
    
    return 0;
}

int pa__init(pa_module *m) {
    struct userdata *u = NULL;
    pa_modargs *ma = NULL;
    pa_sink_new_data sink_data;
    pa_source_new_data source_data;
    pa_sample_spec ss;
    pa_channel_map map;
    struct pollfd *pollfd;
    pa_sink_flags_t sink_flags = PA_SINK_LATENCY;
    pa_source_flags_t source_flags = PA_SOURCE_LATENCY;
    
    pa_assert(m);
    
    if (!(ma = pa_modargs_new(m->argument, valid_modargs))) {
        pa_log("Failed to parse module arguments.");
        goto fail;
    }
    
    ss = m->core->default_sample_spec;
    map = m->core->default_channel_map;
    
    if (pa_modargs_get_sample_spec_and_channel_map(ma, &ss, &map, PA_CHANNEL_MAP_DEFAULT) < 0) {
        pa_log("Invalid sample format specification or channel map");
        goto fail;
    }
    
    u = pa_xnew0(struct userdata, 1);
    u->core = m->core;
    u->module = m;
    m->userdata = u;
    u->rtpoll = pa_rtpoll_new();
    pa_thread_mq_init(&u->thread_mq, m->core->mainloop, u->rtpoll);
    
    u->lambda_command = pa_xstrdup(pa_modargs_get_value(ma, "lambda_command", NULL));
    if (!u->lambda_command) {
        pa_log("No lambda_command specified");
        goto fail;
    }
    
    if (spawn_lambda(u) < 0)
        goto fail;
    
    pa_sink_new_data_init(&sink_data);
    sink_data.driver = __FILE__;
    sink_data.module = m;
    pa_sink_new_data_set_name(&sink_data, pa_modargs_get_value(ma, "sink_name", DEFAULT_SINK_NAME));
    pa_sink_new_data_set_sample_spec(&sink_data, &ss);
    pa_sink_new_data_set_channel_map(&sink_data, &map);
    pa_proplist_sets(sink_data.proplist, PA_PROP_DEVICE_DESCRIPTION, "Lambda Sink");
    pa_proplist_sets(sink_data.proplist, PA_PROP_DEVICE_CLASS, "abstract");
    
    if (pa_modargs_get_proplist(ma, "sink_properties", sink_data.proplist, PA_UPDATE_REPLACE) < 0) {
        pa_log("Invalid properties");
        pa_sink_new_data_done(&sink_data);
        goto fail;
    }
    
    u->sink = pa_sink_new(m->core, &sink_data, sink_flags);
    pa_sink_new_data_done(&sink_data);
    
    if (!u->sink) {
        pa_log("Failed to create sink.");
        goto fail;
    }
    
    u->sink->parent.process_msg = sink_process_msg;
    u->sink->update_requested_latency = sink_update_requested_latency_cb;
    u->sink->request = sink_request_cb;
    u->sink->userdata = u;
    
    pa_sink_set_asyncmsgq(u->sink, u->thread_mq.inq);
    pa_sink_set_rtpoll(u->sink, u->rtpoll);
    
    pa_source_new_data_init(&source_data);
    source_data.driver = __FILE__;
    source_data.module = m;
    pa_source_new_data_set_name(&source_data, pa_modargs_get_value(ma, "source_name", DEFAULT_SOURCE_NAME));
    pa_source_new_data_set_sample_spec(&source_data, &ss);
    pa_source_new_data_set_channel_map(&source_data, &map);
    pa_proplist_sets(source_data.proplist, PA_PROP_DEVICE_DESCRIPTION, "Lambda Source");
    pa_proplist_sets(source_data.proplist, PA_PROP_DEVICE_CLASS, "abstract");
    
    if (pa_modargs_get_proplist(ma, "source_properties", source_data.proplist, PA_UPDATE_REPLACE) < 0) {
        pa_log("Invalid properties");
        pa_source_new_data_done(&source_data);
        goto fail;
    }
    
    u->source = pa_source_new(m->core, &source_data, source_flags);
    pa_source_new_data_done(&source_data);
    
    if (!u->source) {
        pa_log("Failed to create source.");
        goto fail;
    }
    
    u->source->parent.process_msg = source_process_msg;
    u->source->update_requested_latency = source_update_requested_latency_cb;
    u->source->userdata = u;
    
    pa_source_set_asyncmsgq(u->source, u->thread_mq.inq);
    pa_source_set_rtpoll(u->source, u->rtpoll);
    
    u->rtpoll_item_read = pa_rtpoll_item_new(u->rtpoll, PA_RTPOLL_NEVER, 1);
    pollfd = pa_rtpoll_item_get_pollfd(u->rtpoll_item_read, NULL);
    pollfd->fd = u->pipe_from_lambda;
    pollfd->events = POLLIN;
    pollfd->revents = 0;
    
    u->rtpoll_item_write = pa_rtpoll_item_new(u->rtpoll, PA_RTPOLL_NEVER, 1);
    pollfd = pa_rtpoll_item_get_pollfd(u->rtpoll_item_write, NULL);
    pollfd->fd = u->pipe_to_lambda;
    pollfd->events = POLLOUT;
    pollfd->revents = 0;
    
    pa_memchunk_reset(&u->memchunk);
    
    if (!(u->thread = pa_thread_new("lambda", thread_func, u))) {
        pa_log("Failed to create thread.");
        goto fail;
    }
    
    pa_sink_put(u->sink);
    pa_source_put(u->source);
    
    pa_modargs_free(ma);
    
    return 0;
    
fail:
    if (ma)
        pa_modargs_free(ma);
    
    pa__done(m);
    
    return -1;
}

void pa__done(pa_module *m) {
    struct userdata *u;
    
    pa_assert(m);
    
    if (!(u = m->userdata))
        return;
    
    if (u->sink)
        pa_sink_unlink(u->sink);
    
    if (u->source)
        pa_source_unlink(u->source);
    
    if (u->thread) {
        pa_asyncmsgq_send(u->thread_mq.inq, NULL, PA_MESSAGE_SHUTDOWN, NULL, 0, NULL);
        pa_thread_free(u->thread);
    }
    
    pa_thread_mq_done(&u->thread_mq);
    
    if (u->sink)
        pa_sink_unref(u->sink);
    
    if (u->source)
        pa_source_unref(u->source);
    
    if (u->memchunk.memblock)
        pa_memblock_unref(u->memchunk.memblock);
    
    if (u->rtpoll_item_read)
        pa_rtpoll_item_free(u->rtpoll_item_read);
    
    if (u->rtpoll_item_write)
        pa_rtpoll_item_free(u->rtpoll_item_write);
    
    if (u->rtpoll)
        pa_rtpoll_free(u->rtpoll);
    
    if (u->lambda_pid > 0) {
        kill(u->lambda_pid, SIGTERM);
        waitpid(u->lambda_pid, NULL, 0);
    }
    
    if (u->pipe_to_lambda >= 0)
        pa_close(u->pipe_to_lambda);
    
    if (u->pipe_from_lambda >= 0)
        pa_close(u->pipe_from_lambda);
    
    pa_xfree(u->lambda_command);
    pa_xfree(u);
}