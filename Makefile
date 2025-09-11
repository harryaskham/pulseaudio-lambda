CC = gcc
CFLAGS = -g -O2 -Wall -fPIC -std=c99

# Use PA_CFLAGS if available (from Nix build), otherwise use pkg-config
ifndef PA_CFLAGS
	PA_CFLAGS = $(shell pkg-config --cflags libpulse)
	PA_LIBS = $(shell pkg-config --libs libpulse)
	# For standalone client build
	PA_SIMPLE_LIBS = $(shell pkg-config --libs libpulse-simple)
else
	PA_LIBS = $(shell pkg-config --libs libpulse)
endif

# Build both module and standalone client
MODULE = module-lambda.so
CLIENT = pulseaudio-lambda

MODULE_SOURCES = src/module-lambda.c
CLIENT_SOURCES = src/pulseaudio-lambda.c

MODULE_OBJECTS = $(MODULE_SOURCES:.c=.o)
CLIENT_OBJECTS = $(CLIENT_SOURCES:.c=.client.o)

.PHONY: all clean install test help

all: $(CLIENT)

# Default target is standalone client for now
$(CLIENT): $(CLIENT_OBJECTS)
	$(CC) -o $@ $(CLIENT_OBJECTS) $(PA_LIBS) $(PA_SIMPLE_LIBS)

# Module target (requires pulsecore headers)
module: $(MODULE)

$(MODULE): $(MODULE_OBJECTS)
	$(CC) -shared -o $@ $(MODULE_OBJECTS) $(PA_LIBS)

# Pattern rules
%.o: %.c
	$(CC) $(CFLAGS) $(PA_CFLAGS) -c -o $@ $<

%.client.o: %.c
	$(CC) $(CFLAGS) $(shell pkg-config --cflags libpulse libpulse-simple) -c -o $@ $<

clean:
	rm -f $(CLIENT) $(MODULE) $(CLIENT_OBJECTS) $(MODULE_OBJECTS)
	rm -f compile_commands.json

install: $(MODULE)
	@echo "Installing module to system..."
	@PA_MODULE_DIR=$$(pkg-config --variable=modlibexecdir libpulse 2>/dev/null || echo "/usr/lib/pulse-$(shell pkg-config --modversion libpulse)/modules"); \
	echo "Module directory: $$PA_MODULE_DIR"; \
	sudo mkdir -p "$$PA_MODULE_DIR"; \
	sudo install -m 644 $(MODULE) "$$PA_MODULE_DIR/"
	@echo "Module installed. You can now load it with:"
	@echo "  pactl load-module module-lambda source_name=lambda_source sink_name=lambda_sink lambda_command=/path/to/lambda"

test: $(MODULE)
	@echo "Testing module build..."
	@if [ -f $(MODULE) ]; then \
		echo "✓ Module compiled successfully"; \
		ldd $(MODULE) | grep -q pulse && echo "✓ PulseAudio libraries linked" || echo "✗ PulseAudio libraries not found"; \
	else \
		echo "✗ Module compilation failed"; \
		exit 1; \
	fi
	@echo ""
	@echo "To test the module:"
	@echo "1. Load module: pactl load-module ./$(MODULE) source_name=test_source sink_name=test_sink lambda_command='$(shell pwd)/lambdas/identity.sh'"
	@echo "2. Check it appears: pactl list modules | grep lambda"
	@echo "3. Route audio: paplay --device=test_sink /path/to/test.wav"
	@echo "4. Monitor output: parec --device=test_source.monitor"
	@echo "5. Unload when done: pactl unload-module module-lambda"

# Generate compile_commands.json for LSP support
compile_commands.json:
	bear -- make clean all

help:
	@echo "PulseAudio Lambda Module Build System"
	@echo "===================================="
	@echo ""
	@echo "Targets:"
	@echo "  all     - Build the module (default)"
	@echo "  clean   - Remove built files"
	@echo "  install - Install module system-wide (requires sudo)"
	@echo "  test    - Test build and show usage instructions" 
	@echo "  help    - Show this help"
	@echo ""
	@echo "Development:"
	@echo "  Use 'nix develop' for development environment"
	@echo "  Use 'bear -- make' to generate compile_commands.json"