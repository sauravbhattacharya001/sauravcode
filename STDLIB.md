# Standard Library Reference

Complete reference for all 95 built-in functions in sauravcode. No imports needed — all functions are available immediately.

Sauravcode uses space-separated arguments with no parentheses or commas:

```
upper "hello"           // → "HELLO"
replace "abc" "b" "x"   // → "axc"
range 1 5               // → [1, 2, 3, 4]
```

## String Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `upper` | `upper str` | Convert to uppercase |
| `lower` | `lower str` | Convert to lowercase |
| `trim` | `trim str` | Remove leading/trailing whitespace |
| `replace` | `replace str old new` | Replace all occurrences |
| `split` | `split str delimiter` | Split string into list |
| `join` | `join delimiter list` | Join list into string |
| `contains` | `contains str sub` | Check if string/list/map contains value |
| `starts_with` | `starts_with str prefix` | Check if string starts with prefix |
| `ends_with` | `ends_with str suffix` | Check if string ends with suffix |
| `substring` | `substring str start end` | Extract substring [start:end] |
| `index_of` | `index_of str sub` | Find index of substring (-1 if not found) |
| `char_at` | `char_at str index` | Get character at index |
| `pad_left` | `pad_left str width [fill]` | Left-pad string to width |
| `pad_right` | `pad_right str width [fill]` | Right-pad string to width |
| `repeat` | `repeat str n` | Repeat string n times |
| `char_code` | `char_code str` | Unicode code point of first character |
| `from_char_code` | `from_char_code n` | Character from Unicode code point |

## Math Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `abs` | `abs n` | Absolute value |
| `round` | `round n [places]` | Round number (optional decimal places) |
| `floor` | `floor n` | Round down to integer |
| `ceil` | `ceil n` | Round up to integer |
| `sqrt` | `sqrt n` | Square root (error if negative) |
| `power` | `power base exp` | Exponentiation |
| `log` | `log n [base]` | Logarithm (natural if no base) |
| `sin` | `sin n` | Sine (radians) |
| `cos` | `cos n` | Cosine (radians) |
| `tan` | `tan n` | Tangent (radians) |
| `pi` | `pi` | π constant (3.14159...) |
| `euler` | `euler` | Euler's number e (2.71828...) |
| `clamp` | `clamp value min max` | Clamp value to [min, max] |
| `lerp` | `lerp a b t` | Linear interpolation between a and b |
| `remap` | `remap val inMin inMax outMin outMax` | Remap value from one range to another |
| `min` | `min a b` or `min list` | Minimum of two values or list |
| `max` | `max a b` or `max list` | Maximum of two values or list |

## Collection Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `range` | `range end` / `range start end` / `range start end step` | Generate number list |
| `reverse` | `reverse val` | Reverse a list or string |
| `sort` | `sort list` | Sort a list |
| `zip` | `zip list1 list2` | Pair elements from two lists |
| `enumerate` | `enumerate list` | List of [index, value] pairs |
| `flatten` | `flatten list` | Flatten nested list one level |
| `unique` | `unique list` | Remove duplicates (preserves order) |
| `count` | `count list value` | Count occurrences of value |
| `sum` | `sum list` | Sum all numbers in list |
| `any` | `any list` | True if any element is truthy |
| `all` | `all list` | True if all elements are truthy |
| `slice` | `slice list start [end]` | Extract sub-list |
| `chunk` | `chunk list size` | Split list into chunks |
| `find` | `find func list` | First element where func returns truthy |
| `find_index` | `find_index func list` | Index of first match (-1 if not found) |

## Map (Dictionary) Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `keys` | `keys map` | List of all keys |
| `values` | `values map` | List of all values |
| `has_key` | `has_key map key` | Check if map contains key |

## Higher-Order Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `map` | `map func list` | Apply function to each element, return new list |
| `filter` | `filter func list` | Keep elements where function returns truthy |
| `reduce` | `reduce func list initial` | Fold list with binary function |
| `each` | `each func list` | Apply function to each element (side effects) |

Functions can be passed by name or as lambdas:

```
// By name
function double x
    return x * 2
map double [1 2 3]         // → [2, 4, 6]

// With lambda
map (lambda x -> x * 2) [1 2 3]   // → [2, 4, 6]
filter (lambda x -> x > 2) [1 2 3 4 5]  // → [3, 4, 5]
reduce (lambda acc x -> acc + x) [1 2 3] 0  // → 6
```

## Statistics Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `mean` | `mean list` | Arithmetic mean |
| `median` | `median list` | Median value |
| `mode` | `mode list` | Most frequent value(s) |
| `stdev` | `stdev list` | Standard deviation (population) |
| `variance` | `variance list` | Variance (population) |
| `percentile` | `percentile list p` | p-th percentile (0–100) |

## Random Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `random` | `random` | Random float in [0, 1) |
| `random_int` | `random_int min max` | Random integer in [min, max] |
| `random_choice` | `random_choice list` | Random element from list |
| `random_shuffle` | `random_shuffle list` | Shuffled copy of list |

## Date & Time Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `now` | `now` | Current date/time as ISO string |
| `timestamp` | `timestamp` | Current Unix timestamp (seconds) |
| `date_add` | `date_add date amount unit` | Add time to date (units: years/months/days/hours/minutes/seconds) |
| `date_diff` | `date_diff date1 date2 unit` | Difference between dates in given unit |
| `date_compare` | `date_compare date1 date2` | Compare dates: -1, 0, or 1 |
| `date_format` | `date_format date format` | Format date with strftime pattern |
| `date_part` | `date_part date part` | Extract part (year/month/day/hour/minute/second/weekday) |
| `date_range` | `date_range start end step unit` | List of dates between start and end |

## Regex Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `regex_match` | `regex_match pattern str` | True if entire string matches |
| `regex_find` | `regex_find pattern str` | First match as map `{match, start, end, groups}` |
| `regex_find_all` | `regex_find_all pattern str` | List of all matches |
| `regex_replace` | `regex_replace pattern replacement str` | Replace matches |
| `regex_split` | `regex_split pattern str` | Split string by pattern |

## File I/O Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `read_file` | `read_file path` | Read entire file as string |
| `write_file` | `write_file path content` | Write string to file |
| `append_file` | `append_file path content` | Append string to file |
| `read_lines` | `read_lines path` | Read file as list of lines |
| `file_exists` | `file_exists path` | Check if file exists |

## JSON Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `json_parse` | `json_parse str` | Parse JSON string into value |
| `json_stringify` | `json_stringify val` | Convert to compact JSON string |
| `json_pretty` | `json_pretty val` | Convert to pretty-printed JSON string |

## Encoding Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `base64_encode` | `base64_encode str` | Encode string to Base64 |
| `base64_decode` | `base64_decode str` | Decode Base64 to string |
| `hex_encode` | `hex_encode str` | Encode string to hex |
| `hex_decode` | `hex_decode str` | Decode hex to string |
| `url_encode` | `url_encode str` | URL-encode string |
| `url_decode` | `url_decode str` | URL-decode string |
| `md5` | `md5 str` | MD5 hash (hex digest) |
| `sha1` | `sha1 str` | SHA-1 hash (hex digest) |
| `sha256` | `sha256 str` | SHA-256 hash (hex digest) |
| `crc32` | `crc32 str` | CRC-32 checksum (hex) |

## Utility Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `type_of` | `type_of val` | Type name: number, string, bool, list, map, lambda |
| `to_string` | `to_string val` | Convert any value to string |
| `to_number` | `to_number val` | Convert string/bool to number |
| `input` | `input [prompt]` | Read line from stdin |
| `sleep` | `sleep ms` | Pause execution for milliseconds |

## Operators

Beyond built-in functions, sauravcode supports these operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `+` `-` `*` `/` `%` | Arithmetic | `3 + 4 * 2` |
| `==` `!=` `<` `>` `<=` `>=` | Comparison | `x > 10` |
| `and` `or` `not` | Logical | `x > 0 and x < 100` |
| `\|>` | Pipe | `"hello" \|> upper` |
| `*` on strings/lists | Repetition (guarded) | `"ab" * 3` → `"ababab"` |
| `+` on strings | Concatenation | `"hello" + " " + "world"` |
| `+` on lists | Concatenation | `[1 2] + [3 4]` → `[1, 2, 3, 4]` |
