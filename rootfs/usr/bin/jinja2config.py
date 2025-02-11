#! /usr/bin/python3
import os
import pathlib
import subprocess
import time
import shutil
import tempfile
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ThreadPoolExecutor

HASS_CONFIG_DIR = os.getenv('HASS_CONFIG_DIR')

def check_dependencies():
    if not shutil.which('jinja'):
        print("jinja-cli must be installed: pip install jinja-cli (https://pypi.org/project/jinja-cli/)")
        time.sleep(1)
        exit(1)
    if not shutil.which('prettier'):
        print("Prettier must be installed: apt-get install nodejs npm && npm install -g prettier")
        time.sleep(1)
        exit(1)

def get_output_file(file_path: pathlib.Path):
    output_file = file_path
    if output_file.suffix == '.jinja':
        output_file = output_file.with_suffix('')
    return output_file

def remove(file_path: pathlib.Path):
    output_file = get_output_file(file_path)
    print(f"{file_path} deleted, removing: {output_file}")
    os.remove(output_file)

def compile(file_path: pathlib.Path):
    output_file = get_output_file(file_path)
    print(f"Compiling {file_path} to: {output_file}")
    error_log_file = file_path.parent / f"{file_path.name}.errors.log"
    result_content = f"# DO NOT EDIT: Generated from: {file_path.name}\n"
    result = subprocess.run(['jinja', str(file_path)], capture_output=True)
    if result.returncode == 0:
        result_content += result.stdout.decode()
        if os.path.exists(error_log_file):
            os.remove(error_log_file)
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w+t', delete_on_close=False, suffix=".yaml") as f:
            f.write(result_content)
            f.flush()
            f.close()
            print(f"Using Prettier to formatting temp file '{f.name}' for '{output_file.name}'...")
            subprocess.run(['prettier', '--write', f.name, '--log-level', 'warn'])
            print(f"Copying temp file '{f.name}' to '{output_file}'...")
            shutil.copyfile(f.name, output_file)
    else:
        if output_file.exists():
            os.remove(output_file)
        print(f"Error compiling {file_path}!")
        with open(error_log_file, 'wb') as err_f:
            err_f.write(result.stderr)
        print(result.stderr.decode())

def recompile(file_path: pathlib.Path):
    print(f"Recompiling {file_path} due to changes")
    compile(file_path)

@dataclass
class ChangeRecorder:
    path: pathlib.Path
    deleted: bool = False
    initial_compile: bool = False
    
QUEUE: list[ChangeRecorder] = []
WINDOW_START: float | None = None


class JinjaEventHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path)))

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path)))

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path), deleted=True))

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.dest_path)))
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path), deleted=True))

def process_change(change: ChangeRecorder):
    if change.deleted:
        remove(change.path)
    else:
        if change.initial_compile:
            compile(change.path)
        else:
            recompile(change.path)

def process_changes(changes: list[ChangeRecorder]):
    deduped = {}
    for change in changes:
        deduped[change.path] = change

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_change, change) for change in deduped.values()]
        for future in futures:
            future.result()

def main():
    global QUEUE, WINDOW_START
    check_dependencies()
    print(f"Compiling Jinja templates to YAML: {HASS_CONFIG_DIR}/**/*.yaml.jinja")
    for root, _, files in os.walk(HASS_CONFIG_DIR):
        for file in files:
            if file.endswith('.yaml.jinja'):
                QUEUE.append(ChangeRecorder(pathlib.Path(root) / file, initial_compile=True))

    event_handler = JinjaEventHandler()
    observer = Observer()
    observer.schedule(event_handler, HASS_CONFIG_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
            if QUEUE:
                if WINDOW_START is None:
                    WINDOW_START = time.time()
                elif time.time() - WINDOW_START > 5:
                    queue = QUEUE
                    QUEUE = []
                    process_changes(queue)
                    WINDOW_START = None
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()