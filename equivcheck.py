from dataclasses import dataclass
from typing import List, Set, Tuple, Optional
import re
import click
from collections import deque
import subprocess
import sys
from automata.fa.dfa import DFA

# Boring parts written by Claude.ai!


@dataclass
class Transition:
    src: int
    dst: int
    chars: Set[int]


@dataclass
class ParsedDFA:
    transitions: List[Transition]
    finalnodes: List[Tuple[int, str]]


def parse_char_ranges(range_str: str) -> Set[int]:
    """Parse a character range specification like [0x00-`] into a set of character codes"""
    chars = set()
    # Remove brackets
    range_str = range_str.strip("[]")

    def p(s: str) -> int:
        if s.startswith("0x"):
            return int(s, 16)
        else:
            return ord(s)

    # Split by '][' to handle multiple ranges
    for part in range_str.split("]["):
        if "-" in part:
            a, b = part.split("-")
            start, end = sorted([p(a), p(b)])
            chars.update(set(range(start, end + 1)))
        else:
            chars.update(set([p(part)]))

    return chars


def parse_re2c_graphs(text: str) -> List[ParsedDFA]:
    dfas = []
    lines = deque(text.strip().split("\n"))
    while True:
        dfa = parse_re2c_graph(lines)
        if dfa is None:
            break
        dfas.append(dfa)
    return dfas


def parse_re2c_graph(lines: deque) -> Optional[ParsedDFA]:
    """Parse re2c graph format into final-state nodes and transitions"""
    transitions = []
    finalnodes = []

    # Regular expressions for parsing
    edge_pattern = re.compile(r'(\d+)\s*->\s*(\d+)(?:\s*\[label="([^"]+)"\])?')
    node_pattern = re.compile(r'(\d+)\s*\[label="([^"]+)"\]')

    while len(lines) > 0:
        line = lines.popleft().strip()
        if line == "}":
            return ParsedDFA(transitions, finalnodes)

        # Skip digraph declarations and empty lines
        if (
            line.startswith("digraph")
            or line.startswith("//")
            or line.startswith("/*")
            or not line
        ):
            continue

        # Parse edge definitions
        edge_match = edge_pattern.match(line)
        if edge_match:
            src, dst, label = edge_match.groups()
            src, dst = int(src), int(dst)

            if label:
                # Parse character ranges from label
                chars = set()
                for range_str in label.split():
                    if range_str.startswith("yyacept="):
                        continue
                    if "[" in range_str:
                        chars.update(parse_char_ranges(range_str))
                transitions.append(Transition(src, dst, chars))
            else:
                # Handle transitions without character ranges
                transitions.append(Transition(src, dst, set()))
            continue

        # Parse final-node definitions
        node_match = node_pattern.match(line)
        if node_match:
            node_id, label = node_match.groups()
            finalnodes.append((int(node_id), label))

    return None


def obtain_re2c_dot_output(filename: str, utf8: bool) -> Optional[str]:
    if filename.endswith(".dot"):
        with open(filename, "r") as f:
            return f.read()

    extraflags = ""
    if utf8:
        extraflags += " -8"

    # for non-dot files, feed it to re2c and see what we get.
    try:
        output = subprocess.check_output(f"re2c -D{extraflags} {filename}", shell=True)
        output = output.decode("utf-8")
        return output
    except subprocess.CalledProcessError as e:
        click.echo(f"Error running re2c: {e}")
        return None
    except Exception as e:
        click.echo(f"An error occurred: {e}")
        return None


def parsed_dfa_to_automaton(pdfa: ParsedDFA) -> DFA:
    mk_state = lambda x: str(x)
    states = set()
    input_symbols = set()
    final_states = set(mk_state(n[0]) for n in pdfa.finalnodes)
    nonstarters = set()

    for t in pdfa.transitions:
        states.add(mk_state(t.src))
        states.add(mk_state(t.dst))
        for x in t.chars:
            input_symbols.add(chr(x))
        nonstarters.add(mk_state(t.dst))

    transitions = {state: {} for state in states}

    # DFA library wants explicit transitions from final states.
    # We'll initialize self-loops, which may be overridden below.
    for fs in final_states:
        for sym in input_symbols:
            transitions[fs][sym] = fs

    for t in pdfa.transitions:
        src = mk_state(t.src)
        # empty set here means unconditional transition, not missing!
        if len(t.chars) == 0:
            for sym in input_symbols:
                transitions[src][sym] = mk_state(t.dst)
        else:
            for sym in t.chars:
                transitions[src][chr(sym)] = mk_state(t.dst)

    starters = list(states - nonstarters)
    if len(starters) > 1:
        raise Exception(f"parsed DFA had multiple potential start symbols! {starters}")
    assert (
        len(starters) == 1
    ), "for this DFA we need re2c to tell us which symbol is the start node"
    initial_state = starters[0]

    return DFA(
        states=states,
        input_symbols=input_symbols,
        transitions=transitions,
        initial_state=initial_state,
        final_states=final_states,
    )


@click.command()
@click.argument("filename", type=click.Path(exists=True))
@click.option("--dump", is_flag=True, help="Dump detailed character set information")
def main(filename: str, dump: bool):
    """Parse and analyze re2c-generated graph files."""

    input_text = obtain_re2c_dot_output(filename, utf8="utf8" in filename)
    if not input_text:
        sys.exit(1)

    parsed = parse_re2c_graphs(input_text)

    for pdfa in parsed:
        if dump:
            click.echo("Final Nodes:")
            for node_id, label in pdfa.finalnodes:
                print(f"\tNode {node_id}: {label}")

            click.echo("\nTransitions:")
            for t in pdfa.transitions:
                print(f"\tFrom {t.src} to {t.dst}: {len(t.chars)} characters")
                if dump:
                    # Sort characters for readability
                    char_list = sorted(t.chars)
                    # Print both numeric and character representation when possible
                    chars_str = ", ".join(
                        f"{c} ('{chr(c)}'" if 32 <= c <= 126 else f"{c}"
                        for c in char_list[:10]  # Limit to first 10 for readability
                    )
                    if len(char_list) > 10:
                        chars_str += f", ... ({len(char_list) - 10} more)"
                    print(f"\t  Characters: {chars_str}")

    if len(parsed) == 2:
        a = parsed_dfa_to_automaton(parsed[0])
        z = parsed_dfa_to_automaton(parsed[1])

        zad = z.difference(a)
        if not zad.isempty():
            click.echo("smallest non-empty string accepted by only first automaton:")
            click.echo(zad.successor("", strict=True))

        adz = a.difference(z)
        if not adz.isempty():
            click.echo("smallest non-empty string accepted by only second automaton:")
            click.echo(adz.successor("", strict=True))

        equiv1 = a.union(z) == a and z.union(a) == z
        equiv2 = adz.isempty() and zad.isempty()
        assert equiv1 == equiv2

        print("DFAs equivalent?", equiv1)


if __name__ == "__main__":
    main()


def test_range_parsing():
    assert parse_char_ranges("[b]") == set([ord("b")])
    assert len(parse_char_ranges("[0x00-0x03][0x05-0x07]")) == 7
    assert len(parse_char_ranges("[a-c][e-g]")) == 6
    assert len(parse_char_ranges("[0x00-0xFF]")) == 256
    assert len(parse_char_ranges("[0x00-a][c-0xFF]")) == 255
