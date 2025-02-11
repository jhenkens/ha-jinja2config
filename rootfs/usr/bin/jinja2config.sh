#!/command/with-contenv bashio
HASS_CONFIG_DIR=$(bashio::config 'config_dir')
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
export HASS_CONFIG_DIR
python3 "${SCRIPT_DIR}/jinja2config.py"
