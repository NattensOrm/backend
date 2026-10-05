# -*- coding: utf8 -*-

import re

# Max length of the lines kept (Discord embeds stop at 4096 chars)
LOG_MAX_LENGTH = 2000

LEVEL_EMOJIS = {
    'WARN': '🟧',
    'WARNING': '🟧',
    'ERROR': '🟥',
    'FATAL': '🟥',  # git errors ('fatal: ...')
    'INFO': '🟩',
    'DEBUG': '🟦',
    'TRACE': '🟦',
    }


def log_emoji(line):
    # Explicit 'level=xxx' first, so words in the text (ex: a commit message
    # with 'error' in it) do not change the colour
    match = re.search(r'\blevel=(\w+)', line, re.IGNORECASE)
    if match and match.group(1).upper() in LEVEL_EMOJIS:
        return LEVEL_EMOJIS[match.group(1).upper()]

    # Otherwise, we guess from the words in the line
    for level in ('WARN', 'ERROR', 'FATAL', 'INFO', 'DEBUG', 'TRACE'):
        if level in line.upper():
            return LEVEL_EMOJIS[level]
    return '⬜'


def log_pretty(log):
    # We do this to filter out ANSI sequences (ex: colors)
    reaesc = re.compile(r'\x1b[^m]*m')
    lines = reaesc.sub('', log).splitlines()

    # We do this to have the latest lines, not the first
    exec_stdout_pretty = []
    content_length = 0  # to count the final message length
    for line in reversed(lines):
        newline = f'{log_emoji(line)} {line}\n'
        if content_length + len(newline) > LOG_MAX_LENGTH:
            if not exec_stdout_pretty:
                # Last line alone is too long: we keep its end
                newline = f'{log_emoji(line)} …{line[-LOG_MAX_LENGTH // 2:]}\n'
                exec_stdout_pretty.append(newline)
            break
        content_length += len(newline)
        exec_stdout_pretty.append(newline)
    exec_stdout_pretty.reverse()

    skipped = len(lines) - len(exec_stdout_pretty)
    if skipped > 0:
        exec_stdout_pretty.insert(0, f'⬜ … {skipped} earlier lines skipped\n')

    return exec_stdout_pretty
