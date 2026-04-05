# RuneLite - Remove/Merge Properties Entries

This script allows you to remove or merge entries from the RuneLite `.properties` file.  
The use case is to remove RLPL and sideloaded plugin data from your setup.

## Setup

If using a virtual environment:

- Create venv (e.g. `uv venv --python 3.14`)
- Activate venv with `.venv\Scripts\activate`

## Execution

```sh
python props_tool.py split <file.properties> [--prefix el] [--out split_out.properties]
python props_tool.py split <file.properties> --prefix-file prefixes.txt [--out split_out.properties]
python props_tool.py merge <file.properties> <split_file.properties>
```
