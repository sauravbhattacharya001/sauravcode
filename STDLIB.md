# Standard Library Reference

Complete reference for all 112 built-in functions in sauravcode. No imports needed — all functions are available immediately.

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
| `group_by` | `group_by func list` | Group elements by function result into a map |
| `take_while` | `take_while func list` | Take elements from start while func returns true |
| `drop_while` | `drop_while func list` | Drop elements from start while func returns true |
| `scan` | `scan func initial list` | Like reduce but returns list of intermediate results |
| `zip_with` | `zip_with func list1 list2` | Combine two lists element-wise using func |

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

## Path & Filesystem Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `path_join` | `path_join part1 part2 ...` | Join path components with OS separator |
| `path_dir` | `path_dir path` | Get directory portion of a path |
| `path_base` | `path_base path` | Get filename portion of a path |
| `path_ext` | `path_ext path` | Get file extension (e.g. `.txt`) |
| `path_stem` | `path_stem path` | Get filename without extension |
| `path_abs` | `path_abs path` | Get absolute path |
| `path_exists` | `path_exists path` | Check if path exists |
| `list_dir` | `list_dir path` | List entries in a directory (sorted) |
| `make_dir` | `make_dir path` | Create directory (and parents) |
| `is_dir` | `is_dir path` | Check if path is a directory |
| `is_file` | `is_file path` | Check if path is a regular file |

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

## Set Data Structure

Sets are unordered collections of unique, hashable values (numbers, strings, booleans). Created from lists, they support mathematical set operations.

| Function | Usage | Description |
|----------|-------|-------------|
| `sets_create` | `sets_create list` | Create a set from a list (deduplicates) |
| `sets_add` | `sets_add (s) (val)` | New set with value added |
| `sets_remove` | `sets_remove (s) (val)` | New set with value removed (no error if missing) |
| `sets_contains` | `sets_contains (s) (val)` | Check if value is in set → true/false |
| `sets_union` | `sets_union (a) (b)` | Elements in either set |
| `sets_intersection` | `sets_intersection (a) (b)` | Elements in both sets |
| `sets_difference` | `sets_difference (a) (b)` | Elements in a but not b |
| `sets_symmetric_diff` | `sets_symmetric_diff (a) (b)` | Elements in either but not both |
| `sets_size` | `sets_size s` | Number of elements |
| `sets_to_list` | `sets_to_list s` | Convert to sorted list |
| `sets_is_subset` | `sets_is_subset (a) (b)` | True if a ⊆ b |
| `sets_is_superset` | `sets_is_superset (a) (b)` | True if a ⊇ b |

## UUID & Random Data Generation

| Function | Usage | Description |
|----------|-------|-------------|
| `uuid_v4` | `uuid_v4` | Generate random UUID v4 string (no args) |
| `random_bytes` | `random_bytes 16` | List of n random integers 0-255 |
| `random_hex` | `random_hex 8` | Random hex string (2n hex characters) |
| `random_string` | `random_string 32` | Random alphanumeric string of length n |
| `random_float` | `random_float` or `random_float 1.0 100.0` | Random float in [0,1) or [min,max) |

## CSV Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `csv_parse` | `csv_parse text` or `csv_parse text ","` | Parse CSV text into list of maps (first row = headers). Auto-converts numbers. |
| `csv_stringify` | `csv_stringify (rows)` or `csv_stringify (rows) ","` | Convert list of maps back to CSV text |
| `csv_headers` | `csv_headers (rows)` | Extract column names from parsed CSV data |
| `csv_select` | `csv_select (rows) ["col1", "col2"]` | Select specific columns from CSV data |
| `csv_filter` | `csv_filter (rows) "column" value` | Filter rows where column equals value |
| `csv_sort` | `csv_sort (rows) "column"` or `csv_sort (rows) "column" "desc"` | Sort rows by column (ascending or descending) |
| `csv_read` | `csv_read "file.csv"` | Read and parse a CSV file |
| `csv_write` | `csv_write "file.csv" (rows)` | Write CSV data to a file |

### Validation

| Function | Usage | Description |
|----------|-------|-------------|
| `is_email` | `is_email "user@example.com"` | True if valid email address |
| `is_url` | `is_url "https://example.com"` | True if valid HTTP/HTTPS URL |
| `is_ipv4` | `is_ipv4 "192.168.1.1"` | True if valid IPv4 address |
| `is_ipv6` | `is_ipv6 "::1"` | True if valid IPv6 address |
| `is_ip` | `is_ip "10.0.0.1"` | True if valid IPv4 or IPv6 address |
| `is_date` | `is_date "2026-03-21"` | True if parseable date (YYYY-MM-DD, MM/DD/YYYY, etc.) |
| `is_uuid` | `is_uuid "550e8400-..."` | True if valid UUID format |
| `is_hex_color` | `is_hex_color "#ff0000"` | True if valid hex color (#RGB, #RRGGBB, #RRGGBBAA) |
| `is_phone` | `is_phone "+14155551234"` | True if valid phone number format |
| `is_credit_card` | `is_credit_card "4111111111111111"` | True if valid card number (Luhn algorithm) |
| `is_json` | `is_json "[1, 2, 3]"` | True if valid JSON string |
| `validate` | `validate "val" ["required", "email"]` | Multi-rule validation returning `{valid, errors}` |

**Validate rules:** `required`, `email`, `url`, `ipv4`, `ipv6`, `ip`, `uuid`, `date`, `hex_color`, `phone`, `credit_card`, `json`, `numeric`, `alpha`, `alphanumeric`, `min_len:N`, `max_len:N`, `min:N`, `max:N`

### Color Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `color_rgb` | `color_rgb 255 0 0` | Create color from RGB (0-255). Returns `{r, g, b, hex}` |
| `color_hex` | `color_hex "#FF0000"` | Parse hex color string. Returns `{r, g, b, hex}` |
| `color_hsl` | `color_hsl 30 100 50` | Create from HSL (h: 0-360, s: 0-100, l: 0-100). Returns `{h, s, l, r, g, b, hex}` |
| `color_blend` | `color_blend "#FF0000" "#0000FF" 0.5` | Blend two colors by ratio (0-1). Returns hex string |
| `color_lighten` | `color_lighten "#FF0000" 20` | Lighten color by amount (0-100). Returns hex string |
| `color_darken` | `color_darken "#FF0000" 20` | Darken color by amount (0-100). Returns hex string |
| `color_invert` | `color_invert "#FF8800"` | Invert a color. Returns hex string |
| `color_contrast` | `color_contrast "#FFFF00"` | Get best text color (`#000000` or `#FFFFFF`) for readability |
| `color_to_rgb` | `color_to_rgb "#1E90FF"` | Convert hex to `{r, g, b}` map |
| `color_to_hex` | `color_to_hex 30 144 255` | Convert RGB values to hex string |
| `color_to_hsl` | `color_to_hsl "#1E90FF"` | Convert hex to `{h, s, l}` map |

## Regular Expressions

| Function | Example | Description |
|----------|---------|-------------|
| `re_test` | `re_test "\\d+" "hello 42"` | Test if pattern matches anywhere → `true`/`false` |
| `re_match` | `re_match "(\\w+)@(\\w+)" "user@host"` | Match from start → `{matched, groups, start, end}` or `nil` |
| `re_search` | `re_search "\\d+" "abc 42 def"` | Search anywhere → `{matched, groups, start, end}` or `nil` |
| `re_find_all` | `re_find_all "[A-Z]\\w+" "Hello World"` | Find all matches → list of strings (or list of lists for groups) |
| `re_replace` | `re_replace "\\s+" " " "too  many"` | Replace all matches; optional 4th arg limits count |
| `re_split` | `re_split "[,;\\s]+" "a, b; c"` | Split by pattern → list; optional 3rd arg limits splits |
| `re_escape` | `re_escape "$10.00"` | Escape special regex characters for literal matching |

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
