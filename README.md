Probably easiest to use `uv`:

```sh
❯ git clone 
Cloning into 're2c_to_automaton'...
[...]

❯ cd re2c_to_automaton 

❯ uv run python equivcheck.py examples/eq/aba02.re 
Using CPython 3.12.0 interpreter at: /opt/homebrew/opt/python@3.12/bin/python3.12
Creating virtual environment at: .venv
Installed 11 packages in 27ms
DFAs equivalent? True

❯ uv run python equivcheck.py examples/ne/aba02.re
DFAs equivalent? False
```

No features beyond equivalence checking implemented yet.

Consider this code mostly as a starting base to build your own
experimental tooling.
