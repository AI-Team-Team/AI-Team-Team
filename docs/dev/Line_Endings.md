# Line Endings

ATT uses LF line endings for project text files across Linux, macOS, and Windows.

This guide describes the repository settings, the distinction between staged and working-tree content, and ways to inspect or normalize existing files.

LF is the byte `0A`, while CRLF is the two-byte sequence `0D 0A`.

Line-ending style is separate from whether a file ends with a final newline or contains a blank line.

## Repository Settings

The root [.gitattributes](../../.gitattributes) contains:

```gitattributes
* text=auto eol=lf
```

`text=auto` lets Git distinguish text from binary content, and `eol=lf` selects LF for eligible text files when they are checked out.

Git's text normalization applies when content enters the index, which is the staging area for the next commit.

Adding this configuration does not immediately rewrite existing working-tree files or previously staged content.

The [Git attributes documentation](https://git-scm.com/docs/gitattributes#_end_of_line_conversion) describes the conversion rules and how existing files can be renormalized.

The root [.editorconfig](../../.editorconfig) contains:

```ini
root = true

[*]
end_of_line = lf
```

Editors with EditorConfig support can use this setting when saving project files.

`root = true` ends the search for additional EditorConfig files in parent directories.

Final-newline insertion, indentation, and character encoding remain separate settings.

The [EditorConfig documentation](https://editorconfig.org/#supported-properties) describes editor support and the available properties.

## Inspecting Line Endings

The following read-only command reports the indexed and working-tree versions of tracked files:

```bash
git ls-files --eol
```

The report can also be limited to a particular file:

```bash
git ls-files --eol -- .gitignore
git check-attr text eol -- .gitignore
```

`i/` describes the indexed content, `w/` describes the actual working-tree file, and `attr/` describes the applicable Git attributes.

| Example | Meaning |
| --- | --- |
| `i/lf w/lf` | Both versions use LF. |
| `i/crlf w/lf` | The working-tree file uses LF, while the index still contains CRLF. |
| `i/lf w/crlf` | The index contains LF, while the working-tree file uses CRLF. |
| `w/mixed` | Git detected mixed line endings in the working-tree file. |
| `w/none` | The working-tree file has no recognized line separators. |
| `w/-text` | Git classified the working-tree content as non-text. |

An `attr/text=auto eol=lf` entry describes policy rather than confirming the file's current bytes.

Adding `--cached --others --exclude-standard` includes tracked files and untracked files that are not ignored:

```bash
git ls-files --eol --cached --others --exclude-standard
```

For a selected UTF-8 project file, a byte-level check can distinguish CRLF, LF, and standalone CR without changing the file:

```python
from pathlib import Path

data = Path(".gitignore").read_bytes()
crlf = data.count(b"\r\n")
print({
    "CRLF": crlf,
    "LF": data.count(b"\n") - crlf,
    "CR": data.count(b"\r") - crlf,
})
```

Python snippets can run with `./venv/bin/python` on POSIX systems or `.\venv\Scripts\python.exe` on Windows.

Binary reads preserve the original bytes, while ordinary text reads can translate line separators before returning strings, as described in the [Python I/O documentation](https://docs.python.org/3.11/library/io.html#text-i-o).

## Converting Working-Tree Files

An editor's line-ending conversion updates the working-tree file when it is saved.

EditorConfig helps subsequent saves follow the project convention; existing files can still need an explicit conversion.

The following Python example converts one selected UTF-8 text file, preserves its file mode, and replaces it atomically using a temporary file in the same directory:

```python
import os
import stat
import tempfile
from pathlib import Path

path = Path(".gitignore")
if path.is_symlink() or not path.is_file():
    raise ValueError("The selected path must be a regular project text file.")

original = path.read_bytes()
original.decode("utf-8")
if b"\0" in original:
    raise ValueError("The selected file contains binary data.")
converted = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

if converted != original:
    mode = stat.S_IMODE(path.stat().st_mode)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".lf-", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(converted)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staging, mode)
        if path.is_symlink() or path.read_bytes() != original:
            raise RuntimeError("The selected file changed during conversion.")
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
```

The byte replacements preserve UTF-8 content and any UTF-8 byte-order mark already present.

Files using another encoding need an encoding-aware conversion rather than this UTF-8 example.

For a workspace-wide conversion, a reviewed scope can include project source, documentation, and configuration while excluding `.git`, virtual environments, caches, installed dependencies, binary files, and generated archives.

Symbolic links are excluded so conversion does not follow a path to a different file or location.

## Normalizing the Git Index

Working-tree conversion and index normalization are separate operations.

The following commands stage the two configuration files and reapply Git's clean conversion to tracked files under the current directory:

```bash
git add .gitattributes .editorconfig
git add --renormalize .
git diff --cached --stat
git diff --cached
```

`--renormalize` updates the index and leaves working-tree bytes unchanged.

It also stages other current changes to tracked files within the selected scope, and newly created files need a normal `git add` because renormalization implies the tracked-file update mode.

Git's conversion handles CRLF, while standalone CR characters remain unchanged by `--renormalize` and can be handled by an explicit working-tree conversion.

These behaviors are documented in the [`git add` reference](https://git-scm.com/docs/git-add#Documentation/git-add.txt---renormalize).

The cached diff shows the staged result, while another `git ls-files --eol` check shows whether both the index and working tree now use LF.

## Source Files and Runtime Data

The LF convention applies to project text files rather than defining a format for data received at runtime.

Windows processes, native libraries, and external tools can legitimately produce CRLF output.

A text view may normalize that output for comparison, while a retained raw log preserves its original bytes when byte identity matters.

Source literals such as `b"\r\n"` contain escape notation and remain unchanged by file line-ending normalization.

Byte-sensitive fixtures can use an explicit `-text` rule for their paths in `.gitattributes`, with corresponding editor settings for the intended format.
