from collections.abc import Callable
from collections.abc import Iterable
import functools
import logging
import re
import shutil
from typing import Final

import sqlparse


class PrettySQLFormatter(logging.Formatter):
    """Formatter that pretty-prints SQL queries from `django.db.backends`."""

    LINE_WIDTH = 80
    STRING_MAX_LEN = 25
    RICH_LOG_RESERVED_WIDTH = 40
    BOX_MARGIN = 1
    TITLE_MARGIN = 1

    BOX_WIDTH = LINE_WIDTH + BOX_MARGIN * 2 + 2

    def format(self, record: logging.LogRecord) -> str:
        """Format SQL log records with boxed, pretty-printed SQL.

        Args:
            record (logging.LogRecord): The log record being formatted.

        Returns:
            str: The formatted log message.
        """
        original_msg = record.msg
        original_args = record.args

        try:
            if sql := self._extract_sql(record):
                sql = sql.strip()

                truncate_char = '[...]'
                string_len = max(self.STRING_MAX_LEN - len(truncate_char), 0)
                formatted_sql = sqlparse.format(
                    sql,
                    reindent=True,
                    keyword_case='upper',
                    strip_comments=False,
                    use_space_around_operators=True,
                    wrap_after=self.LINE_WIDTH,
                    truncate_strings=string_len,
                    truncate_char=truncate_char,
                )

                duration = getattr(record, 'duration', None)
                if isinstance(duration, int | float):
                    title = f'SQL {duration * 1000:.3f} ms'
                else:
                    title = 'SQL'

                record.msg = '\n%s'
                record.args = (self._make_box(title, formatted_sql),)

            return super().format(record)

        finally:
            record.msg = original_msg
            record.args = original_args

    @classmethod
    def _make_box(cls, title: str, body: str) -> str:
        """Wrap text in a terminal-width box.

        Args:
            title (str): Box title text.
            body (str): Body text to place inside the box.

        Returns:
            str: Boxed text.
        """
        width = cls._get_box_width(cls.BOX_WIDTH)
        line_width = cls._get_line_width(width, cls.BOX_MARGIN)

        # Fit all lines into the box width
        lines = body.splitlines() or []
        lines = sum([cls._wrap_line(line, line_width) for line in lines], [])
        lines = lines or ['']

        # Collect all the box lines together
        top = cls._top_line(title, width)
        bottom = cls._bottom_line(width)
        body_lines = [cls._body_line(line, line_width) for line in lines]
        return '\n'.join([top, *body_lines, bottom])

    @classmethod
    def _get_box_width(cls, preferred_width: int) -> int:
        """Calculate a box width that fits the current terminal.

        Args:
            preferred_width (int): Preferred box width.

        Returns:
            int: Width constrained for terminal output.
        """
        fallback_size = (preferred_width, 24)
        max_width = shutil.get_terminal_size(fallback_size).columns

        # Reserve space for `RichHandler` time, level, path and padding.
        available_width = max_width - cls.RICH_LOG_RESERVED_WIDTH
        return max(24, min(preferred_width, available_width))

    @staticmethod
    @functools.cache
    def _get_line_width(width: int, margin: int) -> int:
        """Return body text width for a box.

        Args:
            width (int): Total box width.
            margin (int): Horizontal margin on each side.

        Returns:
            int: Width available for body text.
        """
        # <------------------ width ------------------->
        # [box][margin][<-- line_width -->][margin][box]
        reserved = margin * 2 + 2
        return max(width, reserved) - reserved

    @classmethod
    def _top_line(cls, title: str, width: int) -> str:
        """Format the top border line for a titled box.

        Args:
            title (str): Title to render in the border.
            width (int): Total box width.

        Returns:
            str: Formatted top border line.
        """
        margin = ' ' * cls.TITLE_MARGIN
        text = f'{margin}{title}{margin}'
        template = cls._top_line_template(len(text), width)
        return template.format(text)

    @staticmethod
    @functools.cache
    def _top_line_template(text_len: int, width: int) -> str:
        """Format a template for the box top border.

        Args:
            text_len (int): Length of the title text.
            width (int): Total box width.

        Returns:
            str: Format string for the top border.
        """
        return '╭{}' + '─' * max(0, width - text_len - 2) + '╮'

    @classmethod
    def _body_line(cls, line: str, inner_width: int) -> str:
        """Format one padded body line for a box.

        Args:
            line (str): Text to include in the body line.
            inner_width (int): Width available for body text.

        Returns:
            str: Formatted body line.
        """
        margin = ' ' * cls.BOX_MARGIN
        return f'│{margin}{line.ljust(inner_width)}{margin}│'

    @staticmethod
    @functools.cache
    def _bottom_line(width: int) -> str:
        """Format a bottom border for a box.

        Args:
            width (int): Total box width.

        Returns:
            str: Formatted bottom border line.
        """
        return '╰' + '─' * (width - 2) + '╯'

    @classmethod
    def _wrap_line(cls, line: str, line_width: int) -> list[str]:
        """Split a line into chunks that fit the box body.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum chunk width.

        Returns:
            list[str]: Wrapped line chunks.
        """
        result = []

        line = cls._normalize_line_indent(line.rstrip(), line_width)
        if not line:
            return result

        indent = cls._calculate_indent(line, line_width)

        while len(line) > line_width:
            wrapped, line = cls._wrap_line_impl(line, line_width)
            result.append(wrapped)
            if line:
                line = indent + line

        if line:
            # Keep the remainder
            result.append(line)
        return result

    @classmethod
    def _normalize_line_indent(cls, line: str, line_width: int) -> str:
        """Limit excessive indentation before wrapping a SQL line.

        `sqlparse` can align continuation lines with very deep indentation,
        especially for long parenthesized DDL statements. The box formatter
        must cap that indentation before it starts looking for wrap points.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum chunk width.

        Returns:
            str: Text line with normalized indent.
        """
        text = line.lstrip()
        if not text:
            return ''

        indent_len = len(line) - len(text)
        indent = line[:indent_len]
        return cls._limit_indent(indent, line_width) + text

    @classmethod
    def _wrap_line_impl(cls, line: str, line_width: int) -> tuple[str, str]:
        """Split one SQL line into a first line and continuation.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum first-line width.

        Returns:
            tuple[str, str]: First line and remaining text.
        """
        break_at = cls._find_whitespace_wrap(line, line_width)
        first = line[:break_at].rstrip()

        if break_at is None or not first:
            break_at = cls._find_identifier_wrap(line, line_width)
            first = line[:break_at].rstrip()

        if break_at is None or not first:
            # Avoid wrapping at leading indentation only. That can split
            # the first SQL token and confuse quoted identifier handling.
            break_at = line_width
            first = line[:break_at].rstrip()

        second = line[break_at:].lstrip()
        return first, second

    @classmethod
    def _find_whitespace_wrap(cls, line: str, line_width: int) -> int | None:
        """Find the best whitespace position for wrapping.

        Prefers the last whitespace character before `width` that is outside
        single-quoted and double-quoted strings.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum chunk width.

        Returns:
            int | None: The index of the whitespace character.
                The whitespace itself should be excluded from
                the previous line and stripped from the next line.
        """
        return cls._find_last_unquoted(line, line_width, str.isspace)

    @classmethod
    def _find_identifier_wrap(cls, line: str, line_width: int) -> int | None:
        """Find a readable fallback wrap point in SQL identifiers.

        This is intentionally weaker than whitespace wrapping. It exists for
        dotted identifiers such as Django-generated table-qualified columns.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum chunk width.

        Returns:
            int | None: Line split position, if any.
        """
        found = cls._find_last_unquoted(line, line_width, '.'.__eq__)
        return found and found + 1

    @classmethod
    def _calculate_indent(cls, line: str, line_width: int) -> str:
        """Calculate indentation for wrapped continuation lines.

        Prefer aligning after SQL keyword. If no keyword is found,
        preserve the original indentation.

        Args:
            line (str): Text line to split.
            line_width (int): Maximum chunk width.

        Returns:
            str: Indentation for continuation lines.
        """
        for matcher in cls._get_indent_matchers():
            if indent := matcher(line):
                break
        else:
            # No keyword found, align with leading whitespace
            indent = cls._get_leading_indent(line)
        return cls._limit_indent(indent, line_width)

    @classmethod
    @functools.cache
    def _get_indent_matchers(cls) -> Iterable[Callable[[str], str | None]]:
        """Return cached indentation matcher functions.

        Returns:
            Iterable[Callable[[str], str | None]]: Indentation matchers.
        """
        return (
            cls._match_parenthesis_indent,
            cls._match_keyword_indent,
        )

    @classmethod
    def _match_parenthesis_indent(cls, line: str) -> str | None:
        """Calculate indentation from SQL parentheses.

        Args:
            line (str): Text line to inspect.

        Returns:
            str | None: Indentation string, if a match is found.
        """
        match = _SQL_PARENTHESIS_ALIGN_RE.search(line)
        if match is None:
            return None

        if cls._is_inside_quotes(line, match.start()):
            return None

        kw_end = match.end()
        chars = line[kw_end:]
        found = cls._find_last_unquoted(chars, len(chars), '('.__eq__)
        if found is not None:
            # Align after opening parenthesis.
            return ' ' * (kw_end + found + 1)

        # Fallback on keyword
        return ' ' * (kw_end + 1)

    @classmethod
    def _match_keyword_indent(cls, line: str) -> str | None:
        """Calculate indentation by a SQL keyword in current line.

        The method ignores keywords inside quoted strings.

        Args:
            line (str): Text line to split.

        Returns:
            str | None: Indentation string, if a match is found.
        """
        for match in _SQL_ALIGN_KEYWORD_RE.finditer(line):
            start = match.start()
            end = match.end()

            if cls._is_inside_quotes(line, start):
                # Quoted string, not a keyword
                continue

            # Align after the keyword plus one space
            return ' ' * min(end + 1, len(line))

        return None

    @staticmethod
    def _get_leading_indent(line: str) -> str:
        """Calculate indentation by leading whitespace in current line.

        Args:
            line (str): Text line to split.

        Returns:
            str: Leading whitespace from the line.
        """
        len_indented = len(line.lstrip())
        indent_len = len(line) - len_indented
        return line[:indent_len]

    @staticmethod
    def _limit_indent(indent: str, line_width: int) -> str:
        """Limit too big indentation string to keep text readable.

        Args:
            indent (str): Whitespace indent string.
            line_width (int): Maximum chunk width.

        Returns:
            str: Indentation constrained to readable width.
        """
        max_indent = max(0, line_width // 2)
        return indent[:max_indent]

    @classmethod
    def _is_inside_quotes(cls, line: str, position: int) -> bool:
        """Return whether a line position is inside SQL quotes.

        Args:
            line (str): SQL text line to inspect.
            position (int): Character position to check.

        Returns:
            bool: True when the position is inside quotes.
        """
        if position < 1:
            return False
        found = cls._find_last_unquoted(line, position)
        return found is None or found < position

    @staticmethod
    def _find_last_unquoted(
        line: str,
        line_width: int,
        predicate: Callable[[str], bool] = lambda _: True,
    ) -> int | None:
        """Find the last matching character outside SQL quotes.

        Args:
            line (str): SQL text line to inspect.
            line_width (int): Search boundary in the line.
            predicate (Callable[[str], bool]): Character matcher.

        Returns:
            int | None: Index of the last unquoted match, if found.
        """
        in_single_quote = False
        in_double_quote = False
        escaped = False
        found: int | None = None

        chars = line[:line_width]
        for index, char in enumerate(chars):
            if escaped:
                escaped = False
                continue

            if char == '\\':
                escaped = True
                continue

            if char == "'" and not in_double_quote:
                # SQL escaping: 'John''s order'
                if (
                    in_single_quote
                    and index + 1 < len(line)
                    and line[index + 1] == "'"
                ):
                    escaped = True
                    continue

                in_single_quote = not in_single_quote
                continue

            if char == '"' and not in_single_quote:
                # SQL escaping for quoted identifiers: "some ""quoted"" name"
                if (
                    in_double_quote
                    and index + 1 < len(line)
                    and line[index + 1] == '"'
                ):
                    escaped = True
                    continue

                in_double_quote = not in_double_quote
                continue

            is_quoted = in_single_quote or in_double_quote
            if predicate(char) and not is_quoted:
                found = index

        return found

    @staticmethod
    def _extract_sql(record: logging.LogRecord) -> str | None:
        """Extract SQL text from a log record from `django.db.backends`.

        Args:
            record (logging.LogRecord): Log record to inspect.

        Returns:
            str | None: SQL text when present.
        """
        sql = getattr(record, 'sql', None)
        if isinstance(sql, str):
            return sql

        if record.args and isinstance(record.args, tuple):
            for arg in record.args:
                if isinstance(arg, str) and _is_sql_statement(arg):
                    return arg

        return None


def _is_sql_statement(text: str) -> bool:
    """Test whether text begins with a known SQL statement.

    Args:
        text (str): Text to inspect.

    Returns:
        bool: True when the value looks like SQL.
    """
    text = text.lstrip().upper()
    return text.startswith(_SQL_STATEMENTS)


_SQL_STATEMENTS: Final[tuple[str, ...]] = (
    'SELECT ',
    'INSERT ',
    'UPDATE ',
    'DELETE ',
    'CREATE ',
    'ALTER ',
    'DROP ',
    'WITH ',
    'SAVEPOINT ',
    'RELEASE ',
    'ROLLBACK ',
    'COMMIT',
    'BEGIN',
)
"""All SQL keywords which can start SQL statement."""

_SQL_ALIGN_KEYWORDS = (
    'CREATE UNIQUE INDEX',
    'CREATE INDEX',
    'CREATE TABLE',
    'ALTER TABLE',
    'ADD CONSTRAINT',
    'FOREIGN KEY',
    'REFERENCES',
    'INSERT INTO',
    'SELECT',
    'FROM',
    'WHERE',
    'JOIN',
    'LEFT JOIN',
    'RIGHT JOIN',
    'INNER JOIN',
    'OUTER JOIN',
    'FULL JOIN',
    'ON',
    'AND',
    'OR',
    'GROUP BY',
    'ORDER BY',
    'HAVING',
    'LIMIT',
    'OFFSET',
    'VALUES',
    'SET',
    'RETURNING',
)
"""All SQL keywords which enforce indentation of child nodes."""

_SQL_ALIGN_KEYWORD_RE = re.compile(
    r'\b('
    + '|'.join(re.escape(keyword) for keyword in _SQL_ALIGN_KEYWORDS)
    + r')\b',
    re.IGNORECASE,
)

_SQL_PARENTHESIS_ALIGN_RE = re.compile(
    r'\b(INSERT\s+INTO|VALUES|CREATE\s+TABLE|WHERE\b.+\bIN)\b',
    re.IGNORECASE,
)
