# Jinja2Config - Home Assistant Add-on

## Project Overview

This is a **Home Assistant add-on** that watches for `*.yaml.jinja` files in the Home Assistant config directory and automatically compiles them to `.yaml` files using the Jinja2 templating engine. This allows users to use templates to reduce repetitive YAML configuration.

## Purpose

Home Assistant configuration can become complex and repetitive, especially when configuring multiple similar entities (e.g., smart thermostats for different rooms, sensors across zones, etc.). This add-on solves that by:

1. Watching for `.yaml.jinja` template files
2. Processing them through Jinja2 with custom variables
3. Generating `.yaml` files that Home Assistant can use
4. Automatically recompiling when templates or variables change
5. Formatting the output with Prettier for readability

## Architecture

### Add-on Structure

This is a **Home Assistant Add-on** built using the Home Assistant Add-on framework:

- **Docker-based**: Runs as a container alongside Home Assistant
- **S6-overlay**: Uses s6-overlay for process supervision
- **File watching**: Continuously monitors the config directory for changes

### Key Components

#### 1. Main Python Script (`rootfs/usr/bin/jinja2config.py`)

The core logic that:
- Watches for `.yaml.jinja` files using `watchdog`
- Loads variables from `jinja2config.yaml` (cached for performance)
- Compiles templates using `j2` (jinjanator) with custom delimiters support
- Formats output with Prettier
- Handles file changes with a 5-second debounce window
- Uses ThreadPoolExecutor for parallel compilation

**Important Implementation Details:**
- Config variables are loaded **once at startup** and cached in `CACHED_CONFIG_VARS`
- Variables are **only reloaded** when `jinja2config.yaml` changes
- All templates are recompiled when the config file changes
- Each template compilation creates a temporary YAML file for j2 to read variables
- Output files have a header comment: `# DO NOT EDIT: Generated from: <template>.yaml.jinja`

#### 2. Shell Wrapper (`rootfs/usr/bin/jinja2config.sh`)

Bash script that:
- Reads add-on configuration using bashio
- Exports `HASS_CONFIG_DIR` environment variable
- Launches the Python script

#### 3. J2 Customizations (`rootfs/etc/jinja2config/j2_customizations.py.template`)

Template file that configures Jinja2 delimiters based on add-on options:
- `variable_start_string` / `variable_end_string` (default: `{{` / `}}`)
- `block_start_string` / `block_end_string` (default: `{%` / `%}`)
- `comment_start_string` / `comment_end_string` (default: `{#` / `#}`)

#### 4. S6 Service (`rootfs/etc/s6-overlay/s6-rc.d/jinja2config/`)

Service definition for s6-overlay:
- `run`: Starts the shell wrapper
- `finish`: Cleanup script
- `type`: Marks it as a long-running service
- `dependencies.d/base`: Ensures base services start first

## File Structure

```
ha-jinja2config/
├── config.yaml                 # Add-on configuration schema
├── build.yaml                  # Build configuration for multiple architectures
├── Dockerfile                  # Container build instructions
├── requirements.txt            # Python dependencies (jinjanator, watchdog, PyYAML)
├── repository.json             # Home Assistant repository metadata
├── jinja2config.yaml.example   # Example variables file for users
├── README.md                   # User-facing documentation
└── rootfs/                     # Files copied into the container
    ├── etc/
    │   ├── jinja2config/
    │   │   └── j2_customizations.py.template  # Jinja2 delimiter configuration
    │   └── s6-overlay/s6-rc.d/
    │       └── jinja2config/   # Service definition
    └── usr/bin/
        ├── jinja2config.py     # Main Python script (228 lines)
        └── jinja2config.sh     # Shell wrapper
```

## Key Features

### 1. Variable Configuration (`jinja2config.yaml`)

Users can create a `jinja2config.yaml` file in their Home Assistant config directory with variables available to all templates:

```yaml
rooms:
  - name: "Living Room"
    id: "living_room"
default_temp: 20
```

These variables are then accessible in any `.yaml.jinja` file:

```yaml
{% for room in rooms %}
- name: {{ room.name }}
  temp: {{ default_temp }}
{% endfor %}
```

### 2. Automatic File Watching

- Watches recursively for all `.yaml.jinja` files
- Watches `jinja2config.yaml` for variable changes
- 5-second debounce window to batch multiple rapid changes
- Parallel compilation using ThreadPoolExecutor

### 3. Custom Delimiters

Users can configure custom Jinja2 delimiters via add-on options to avoid conflicts with other templating systems.

### 4. Error Handling

- Compilation errors are written to `<filename>.yaml.jinja.errors.log`
- If compilation fails, any existing output file is removed
- Error output is displayed in add-on logs

## Dependencies

- **Python packages** (requirements.txt):
  - `jinjanator`: Jinja2 CLI tool with customization support
  - `watchdog`: File system monitoring
  - `PyYAML`: YAML parsing for variable files

- **System packages**:
  - `nodejs` + `npm`: Required for Prettier
  - `prettier`: YAML formatting

## Development Patterns

### Global State Management

```python
CACHED_CONFIG_VARS = {}  # Cached variables from jinja2config.yaml
QUEUE = []               # Queue of file changes to process
WINDOW_START = None      # Start of debounce window
SHUTDOWN = False         # Graceful shutdown flag
```

### Change Processing Flow

1. File system event detected (create/modify/delete)
2. Event added to `QUEUE` with metadata
3. 5-second debounce window allows more changes to accumulate
4. Changes are deduplicated by file path
5. Changes processed in parallel via ThreadPoolExecutor
6. Errors logged, successful compilations formatted with Prettier

### Helper Functions

- `find_all_jinja_templates()`: Reusable function to scan for all `.yaml.jinja` files
- `load_config_variables()`: Updates global cache with variables from config file
- `get_output_file()`: Strips `.jinja` extension to get output filename
- `compile()`: Core compilation logic using cached variables
- `process_changes()`: Deduplicates and parallelizes compilation

## Configuration

Users configure the add-on through Home Assistant's add-on options:

- `log_level`: Logging verbosity (not currently used by Python script)
- `config_dir`: Home Assistant config directory (default: `/config`)
- Custom delimiter strings (optional)

## Common Maintenance Tasks

### Adding New Features

1. Modify `rootfs/usr/bin/jinja2config.py` for core logic changes
2. Update `config.yaml` if new configuration options are needed
3. Update `README.md` to document user-facing changes
4. Test with example `.yaml.jinja` files

### Debugging

- Add-on logs show compilation status and errors
- Error logs created alongside templates: `<file>.yaml.jinja.errors.log`
- Check `HASS_CONFIG_DIR` environment variable is set correctly
- Verify `j2` and `prettier` are installed in container

## Testing Approach

- Manual testing with Home Assistant add-on installation
- Test various Jinja2 templates with different complexity
- Test variable changes trigger recompilation
- Test error handling with invalid templates
- Test custom delimiters
- Test parallel compilation with multiple files

## Home Assistant Integration

This runs as a **long-running add-on** that:
- Has access to the Home Assistant config directory (mapped read-write)
- Runs continuously in the background
- Doesn't expose any API or ports
- Doesn't require Home Assistant integration/HACS
- Is installed from a custom repository

## Future Enhancement Ideas

- Add validation of generated YAML before writing
- Support for includes/imports between templates
- Template linting/validation
- Metrics/statistics on compilation times
- Support for other template engines
- Template dependency graph for smarter recompilation
