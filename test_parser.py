import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location('pageql.parser', 'src/pageql/parser.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)

def test_special_chars_are_expression():
    tokens = parser.tokenize('Hello {{a^b}}')
    assert tokens == [('text', 'Hello '), ('render_expression', 'a^b')]
    tokens = parser.tokenize('Hi {{x[y]}}')
    assert tokens == [('text', 'Hi '), ('render_expression', 'x[y]')]

if __name__ == '__main__':
    test_special_chars_are_expression()
