# Jinja2Config

## About

Watches for ``*.yaml.jinja`` files in your Home Assistant config directory and compiles them
to ``.yaml`` files.

This is useful to simplify complex configuration with repeated components.

If you find this addon useful, please consider supporting the development of this and my other addons and integrations by buying me a coffee

<a href="https://www.buymeacoffee.com/tonyroberts" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50px" width="210px"></a>

## Installation

1. Go to ``Settings`` -> ``Add-ons`` and click the "Add-on Store" button.

2. Select ``Repositories`` using the three dots menu at the top of the page.

3. Add the URL for this github repo to add it.

4. Find the ``jinja2config`` addon now the repository has been added and install it.

## Configuration

The addon supports the following configuration options:

- `log_level`: Set the log level (trace, debug, info, notice, warning, error, fatal). Default: `debug`
- `config_dir`: Path to the Home Assistant config directory. Default: `/config`
- `variable_start_string`: Jinja2 variable start delimiter. Default: `{{`
- `variable_end_string`: Jinja2 variable end delimiter. Default: `}}`
- `block_start_string`: Jinja2 block start delimiter. Default: `{%`
- `block_end_string`: Jinja2 block end delimiter. Default: `%}`
- `comment_start_string`: Jinja2 comment start delimiter. Default: `{#`
- `comment_end_string`: Jinja2 comment end delimiter. Default: `#}`

### Custom Delimiters

You can customize Jinja2 delimiters to avoid conflicts with other templating systems or syntax. For example, to use `((` and `))` for variables:

```yaml
variable_start_string: "(("
variable_end_string: "))"
block_start_string: "<%"
block_end_string: "%>"
comment_start_string: "/*"
comment_end_string: "*/"
```

With these settings, your templates would use the custom delimiters:

```yaml
(( variable ))
<% for item in items %>
  ...
<% endfor %>
/* This is a comment */
```

## Using Variables with jinja2config.yaml

You can create a `jinja2config.yaml` file in your Home Assistant config directory to define variables that will be available to all your Jinja2 templates. This is useful for sharing common values across multiple template files.

### Creating jinja2config.yaml

Create a file named `jinja2config.yaml` in your Home Assistant config directory (typically `/config`):

```yaml
# Example jinja2config.yaml
house_name: "My Smart Home"
default_temp: 20
rooms:
  - name: "Living Room"
    size: 30
  - name: "Bedroom"
    size: 20
heating_zones:
  living_room: "zone_1"
  bedroom: "zone_2"
```

### Using Variables in Templates

In your `.yaml.jinja` templates, you can access these variables directly:

```yaml
# example.yaml.jinja
# Welcome to {{ house_name }}

climate:
  - platform: generic_thermostat
    target_temp: {{ default_temp }}
    
  {% for room in rooms %}
  - name: {{ room.name }}
    size: {{ room.size }}
  {% endfor %}
```

The addon automatically watches `jinja2config.yaml` for changes. When you modify this file, all templates will be automatically recompiled with the new values.

### File-Specific Configuration

You can override or extend variables for specific template files using the `.file_configs` key. This is useful when different templates need different values while still sharing common configuration.

The configurations are **deep-merged**, meaning nested dictionaries are merged recursively rather than replaced entirely.

```yaml
# Global variables
default_temp: 20
rooms:
  - name: "Living Room"
    size: 30

# File-specific overrides
.file_configs:
  # Path relative to config directory
  automations/heating.yaml.jinja:
    default_temp: 22  # Override for this file only
    rooms:  # Deep-merged with global rooms
      - name: "Garage"
        size: 25
    heating_mode: "aggressive"  # File-specific variable
  
  packages/lights.yaml.jinja:
    light_transition: 2
    light_brightness: 200
```

In this example:
- `automations/heating.yaml.jinja` will have `default_temp: 22` (overridden) and access to both the global rooms plus the Garage room
- `packages/lights.yaml.jinja` will have the global `default_temp: 20` plus its file-specific light variables
- All other files use the global configuration

### Skipping Files

You can prevent specific template files from being compiled using the `.skipped_files` key. This is useful for temporarily disabling templates or excluding test/experimental files.

```yaml
# Files to skip (will not be compiled)
.skipped_files:
  - automations/disabled.yaml.jinja
  - packages/experimental.yaml.jinja
  - test/debug.yaml.jinja
```

Files listed in `.skipped_files`:
- Will not be compiled at startup
- Will be ignored when modified
- Paths are relative to your config directory and case-sensitive
- Useful for temporarily disabling templates without deleting them

## Example

I set up smart thermostats to control the underfloor heating for multiple rooms, requiring a certain amount of similar config per room. Using a template the amount of hand written yaml is greatly reduced, making it easier to manage and change as needed.

The following is a sample from my heating system, setting up the climate entities for just two rooms. The complete set up involves more rooms, sensors, switches and, automations. Using templates adding more rooms doesn't require any repeated code.

Any changes to the template result in the yaml file being regenerated automatically. Any errors are written to an error file alongside the template.

```
{% set rooms = [
    {
        "name": "Living Room",
        "id_prefix": "living_room",
        "kp": 100,
        "ki": 0.01,
        "kd": 2500
    },
    {
        "name": "Study",
        "id_prefix": "study",
        "kp": 100,
        "ki": 0.001,
        "kd": 1000
    }
] %}

{% set presets = {
    "min": 7,
    "max": 25,
    "away": 7,
    "eco": 17,
    "sleep": 17,
    "comfort": 19,
    "boost": 21
} %}

climate:
  {% for room in rooms %}
  - platform: smart_thermostat
    name: {{ room.name }} Smart Thermostat
    unique_id: {{ room.id_prefix }}_smart_thermostat
    heater: switch.{{ room.id_prefix }}_heating
    target_sensor: sensor.{{ room.id_prefix }}_temperature
    ac_mode: False
    kp: {{ room.kp }}
    ki: {{ room.ki }}
    kd: {{ room.kd }}
    keep_alive: 00:01:00
    pwm: 00:25:00
    min_cycle_duration: 00:5:00
    {%- for preset in presets %}
    {{ preset }}_temp: {{ presets[preset] }}
    {%- endfor %}
    target_temp: {{ presets["away"] }}
    debug: true
  {% endfor %}
```

## Credits

https://gist.github.com/ndbroadbent/7c80201aca3b4025b943440605f48382
