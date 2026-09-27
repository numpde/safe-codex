# Duration parser

Implement `duration.parse_duration(text)` using only Python's standard library.
Accept one or more nonnegative integer components with lowercase units h, m, s.
Components can touch or have whitespace between them; leading/trailing whitespace
is permitted. Each unit may appear once, in any order. Return total seconds.
Reject empty strings, missing units, duplicate units, negative/fractional numbers,
unknown units, and trailing junk with ValueError. Reject non-string inputs with
TypeError. Examples: `1h30m` -> 5400; `45s 2m` -> 165; `0s` -> 0.
