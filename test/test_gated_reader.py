import asyncio
import os
import shutil
import tempfile
import unittest

from ai_team_team.gated_reader import (
    FileReadRangeError,
    FileReadStatus,
    FileVersionChangedError,
    GatedFileReader,
    TokenCounterUnavailableError,
)


class TokenBoundFileReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="att_file_reader_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write(self, name: str, content: str, *, newline=None) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8", newline=newline) as stream:
            stream.write(content)
        return path

    async def test_many_short_lines_are_limited_by_tokens_not_line_count(self):
        content = "".join(f"{index}\n" for index in range(1, 1_001))
        path = self.write("many.txt", content)
        reader = GatedFileReader(
            max_read_tokens=len(content),
            token_counter=len,
        )

        result = await reader.read_file(path)

        self.assertEqual(result.status, FileReadStatus.COMPLETE)
        self.assertEqual(result.content, content)
        self.assertEqual(result.content_token_count, len(content))

    async def test_long_line_continuation_has_no_gap_or_duplication(self):
        content = "αβγ🙂" * 2_000
        path = self.write("long.txt", content)
        reader = GatedFileReader(max_read_tokens=73, token_counter=len)
        pieces = []
        line = 1
        character = 1
        version = None

        while True:
            result = await reader.read_file(
                path,
                start_line=line,
                start_character=character,
                expected_file_version=version,
            )
            pieces.append(result.content)
            if result.status is FileReadStatus.COMPLETE:
                break
            line = result.next_line
            character = result.next_character
            version = result.file_version

        self.assertEqual("".join(pieces), content)

    async def test_ranges_cannot_bypass_content_token_budget(self):
        path = self.write("range.txt", "0123456789" * 100)
        reader = GatedFileReader(max_read_tokens=17, token_counter=len)

        by_line = await reader.read_file(path, start_line=1, end_line=1)
        by_character = await reader.read_file(
            path, start_line=1, start_character=11, character_count=500
        )

        self.assertEqual(len(by_line.content), 17)
        self.assertEqual(len(by_character.content), 17)
        self.assertEqual(by_character.next_character, 28)

    async def test_conservative_fallback_uses_utf8_bytes(self):
        path = self.write("unicode.txt", "🙂🙂🙂")
        reader = GatedFileReader(max_read_tokens=5)

        result = await reader.read_file(path)

        self.assertEqual(result.content, "🙂")
        self.assertEqual(result.content_token_count, 4)
        self.assertEqual(result.token_count_method, "utf8_bytes_upper_bound")
        self.assertTrue(result.estimated)

    async def test_strict_fallback_rejects_missing_counter(self):
        path = self.write("strict.txt", "content")
        reader = GatedFileReader(tokenizer_fallback="strict")

        with self.assertRaises(TokenCounterUnavailableError):
            await reader.read_file(path)

    async def test_mixed_newlines_use_normalized_continuation_positions(self):
        path = self.write("newlines.txt", "ab\r\ncd\ref\n", newline="")
        reader = GatedFileReader(max_read_tokens=4, token_counter=len)

        first = await reader.read_file(path)
        second = await reader.read_file(
            path,
            start_line=first.next_line,
            start_character=first.next_character,
            expected_file_version=first.file_version,
        )

        self.assertEqual(first.content, "ab\nc")
        self.assertEqual((first.next_line, first.next_character), (2, 2))
        self.assertEqual(second.content, "d\nef")

    async def test_invalid_range_and_changed_version_are_explicit(self):
        path = self.write("versioned.txt", "abcdef")
        reader = GatedFileReader(max_read_tokens=3, token_counter=len)
        first = await reader.read_file(path)

        self.assertEqual(len(first.file_version), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in first.file_version))

        with self.assertRaises(FileReadRangeError):
            await reader.read_file(path, end_line=1, character_count=2)

        counter_calls = 0

        def counting_counter(text):
            nonlocal counter_calls
            counter_calls += 1
            return len(text)

        validating_reader = GatedFileReader(
            max_read_tokens=3,
            token_counter=counting_counter,
        )
        with self.assertRaises(FileReadRangeError):
            await validating_reader.read_file(path, expected_file_version="")
        self.assertEqual(counter_calls, 0)

        self.write("versioned.txt", "changed", newline="")
        with self.assertRaises(FileVersionChangedError):
            await reader.read_file(
                path,
                start_line=first.next_line,
                start_character=first.next_character,
                expected_file_version=first.file_version,
            )

    async def test_counter_protocol_overhead_is_excluded_from_content_count(self):
        path = self.write("overhead.txt", "abc")

        def count_with_overhead(text):
            return len(text) + 1

        reader = GatedFileReader(max_read_tokens=1, token_counter=count_with_overhead)

        result = await reader.read_file(path)

        self.assertEqual(result.status, FileReadStatus.PARTIAL)
        self.assertEqual(result.content, "a")
        self.assertEqual(result.content_token_count, 1)
        self.assertEqual((result.next_line, result.next_character), (1, 2))

    async def test_file_replacement_during_counting_rejects_the_read(self):
        path = self.write("changing.txt", "first version")
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_count(text):
            started.set()
            await release.wait()
            return len(text)

        reader = GatedFileReader(max_read_tokens=20, token_counter=blocking_count)
        read_task = asyncio.create_task(reader.read_file(path))
        await started.wait()
        replacement = self.write("replacement.txt", "second version")
        os.replace(replacement, path)
        release.set()

        with self.assertRaises(FileVersionChangedError):
            await read_task


if __name__ == "__main__":
    unittest.main()
