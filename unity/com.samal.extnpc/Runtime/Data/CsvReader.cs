using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace ExtNPC.Data
{
    /// <summary>
    /// Streaming reader for the CSV dialect the engine writes.
    ///
    /// The engine uses Python's <c>csv.DictWriter</c> with QUOTE_MINIMAL and a
    /// "\n" line terminator, i.e. the RFC-4180 subset: a field is quoted only
    /// when it contains a comma, a double quote or a newline, and an embedded
    /// quote is doubled ("").
    ///
    /// This is deliberately NOT <c>string.Split(',')</c>. Today's exports happen
    /// to contain no quoted field, so a naive split would appear to work and
    /// would break silently the first time a column gained a comma -- shifting
    /// every field after it and mislabelling data rather than failing.
    ///
    /// Streaming, not table-building, is also deliberate. frames.csv for a
    /// 600-person, 600-year world is ~360k rows x 21 columns; materialising
    /// that as a string table costs hundreds of MB in string overhead alone.
    /// Callers read row-by-row straight into typed structs instead, and the
    /// field buffer is reused across rows.
    /// </summary>
    public sealed class CsvReader : IDisposable
    {
        private readonly TextReader _reader;
        private readonly List<string> _fields = new List<string>(32);
        private readonly StringBuilder _field = new StringBuilder(64);
        private readonly Dictionary<string, int> _index =
            new Dictionary<string, int>(StringComparer.Ordinal);

        /// <summary>Header names, in file order.</summary>
        public string[] Columns { get; private set; } = Array.Empty<string>();

        /// <summary>Fields of the row most recently read. Reused -- copy out
        /// anything you intend to keep past the next ReadRow().</summary>
        public IReadOnlyList<string> Current => _fields;

        /// <summary>True when the source held nothing at all (not even a
        /// header). Distinct from a header with zero rows.</summary>
        public bool IsEmpty { get; private set; }

        public CsvReader(TextReader reader)
        {
            _reader = reader ?? throw new ArgumentNullException(nameof(reader));
            if (!ReadRow())
            {
                IsEmpty = true;
                return;
            }
            Columns = new string[_fields.Count];
            for (int i = 0; i < _fields.Count; i++)
            {
                Columns[i] = _fields[i];
                _index[_fields[i]] = i;
            }
        }

        public static CsvReader FromText(string text) =>
            new CsvReader(new StringReader(text ?? string.Empty));

        public static CsvReader FromFile(string path) =>
            new CsvReader(new StreamReader(path, Encoding.UTF8));

        /// <summary>Column index, or -1. Use once and cache; never look a
        /// column up by name inside a per-row loop.</summary>
        public int IndexOf(string column) =>
            _index.TryGetValue(column, out int i) ? i : -1;

        /// <summary>Column index, or throw naming the file's actual header --
        /// a missing column is a contract violation, not a missing value.</summary>
        public int RequireIndex(string column)
        {
            int i = IndexOf(column);
            if (i < 0)
            {
                throw new BundleFormatException(
                    $"required column '{column}' is absent. Header: " +
                    string.Join(", ", Columns));
            }
            return i;
        }

        /// <summary>
        /// Read one record into <see cref="Current"/>. Returns false at EOF.
        /// Handles quoted fields containing commas, doubled quotes and
        /// newlines; tolerates CRLF even though the engine writes LF.
        /// </summary>
        public bool ReadRow()
        {
            _fields.Clear();
            _field.Clear();

            int c = _reader.Read();
            if (c < 0) return false;                    // clean EOF

            bool inQuotes = false;
            bool any = false;

            while (c >= 0)
            {
                char ch = (char)c;
                any = true;

                if (inQuotes)
                {
                    if (ch == '"')
                    {
                        if (_reader.Peek() == '"')      // "" -> literal quote
                        {
                            _reader.Read();
                            _field.Append('"');
                        }
                        else
                        {
                            inQuotes = false;
                        }
                    }
                    else
                    {
                        _field.Append(ch);              // newlines included
                    }
                }
                else if (ch == '"')
                {
                    inQuotes = true;
                }
                else if (ch == ',')
                {
                    PushField();
                }
                else if (ch == '\n')
                {
                    PushField();
                    return true;
                }
                else if (ch == '\r')
                {
                    if (_reader.Peek() == '\n') _reader.Read();
                    PushField();
                    return true;
                }
                else
                {
                    _field.Append(ch);
                }

                c = _reader.Read();
            }

            if (any) PushField();                       // last line, no newline
            return any;
        }

        private void PushField()
        {
            _fields.Add(_field.ToString());
            _field.Clear();
        }

        public void Dispose() => _reader.Dispose();
    }

    /// <summary>Thrown when a bundle is structurally unreadable. Always fail
    /// loudly: a viewer that guesses at a malformed table shows numbers that
    /// are not in the world.</summary>
    public sealed class BundleFormatException : Exception
    {
        public BundleFormatException(string message) : base(message) { }
        public BundleFormatException(string message, Exception inner)
            : base(message, inner) { }
    }
}
