# -*- coding: UTF-8 -*-
"""
The ``jsonschema`` command line.
"""

from __future__ import absolute_import

import argparse
import json
import traceback

import attr
import errno
import sys

from jsonschema import __version__
from jsonschema._reflect import namedAny
from jsonschema.compat import PY3, JSONDecodeError
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for


class _CannotLoadFile(Exception):
    pass


@attr.s
class _Outputter(object):

    _formatter = attr.ib()
    _stdout = attr.ib()
    _stderr = attr.ib()

    @classmethod
    def from_arguments(cls, arguments, stdout, stderr):
        if arguments["output"] == "plain":
            formatter = _PlainFormatter(arguments["error_format"])
        elif arguments["output"] == "pretty":
            formatter = _PrettyFormatter()
        return cls(formatter=formatter, stdout=stdout, stderr=stderr)

    def load(self, path):
        try:
            file = open(path)
        except (IOError, OSError) as error:
            if error.errno != errno.ENOENT:
                raise
            self.filenotfound_error(path=path, exc_info=sys.exc_info())
            raise _CannotLoadFile()

        with file:
            try:
                return json.load(file)
            except JSONDecodeError:
                self.parsing_error(path=path, exc_info=sys.exc_info())
                raise _CannotLoadFile()

    def filenotfound_error(self, **kwargs):
        self._stderr.write(self._formatter.filenotfound_error(**kwargs))

    def parsing_error(self, **kwargs):
        self._stderr.write(self._formatter.parsing_error(**kwargs))

    def validation_error(self, **kwargs):
        self._stderr.write(self._formatter.validation_error(**kwargs))

    def validation_success(self, **kwargs):
        self._stdout.write(self._formatter.validation_success(**kwargs))


@attr.s
class _PrettyFormatter(object):

    _WIDTH = 79
    _HEADER_LINE = '═'
    _MESSAGE_FORMAT = '{}══[{}]═══({})'

    @classmethod
    def _json_formatter(cls, x):
        return json.dumps(x, separators=(',\n', ': '), sort_keys=True)

    def _simple_msg_v3(self, path, type, header=False):
        begin_end_chars = ('╒', '╕') if header is True else ('═', '═')
        return '{}══[{}]═══({})'.format(begin_end_chars[0], type, path) \
                   .ljust(self._WIDTH - 1, '═') + begin_end_chars[1]

    def _simple_msg_v2(self, path, type, header=False):
        begin_end_chars = ('╒', '╕') if header is True else ('═', '═')

        # printed length of the static charaters: left end, brackets, bar characters
        format_length = 11  # TODO: calculate fixed chars printed length
        desired_length = self._WIDTH - len(type) - len(path) - format_length

        return self._MESSAGE_FORMAT.format(begin_end_chars[0], type, path) + \
               self._HEADER_LINE * desired_length + begin_end_chars[1]

    _simple_msg = _simple_msg_v3 if len(_HEADER_LINE) == 1 else _simple_msg_v2

    def _error_msg(self, path, type, body):
        HEADER = self._simple_msg(path, type, header=True)
        FOOTER = '└' + '─' * (self._WIDTH - 2) + '┘'

        return '\n'.join((HEADER, str(body), FOOTER, '\n'))

    def filenotfound_error(self, path, exc_info):
        return self._error_msg(
            path=path,
            type="FileNotFoundError",
            body="{!r} does not exist.".format(path),
        )

    def parsing_error(self, path, exc_info):
        exc_type, exc_value, exc_traceback = exc_info
        exc_lines = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback),
        )
        return self._error_msg(
            path=path,
            type=exc_type.__name__,
            body=exc_lines,
        )

    def validation_error(self, instance_path, error):
        return self._error_msg(
            path=instance_path,
            type=error.__class__.__name__,
            body=error._formatted_message(formatter=self._json_formatter),
        )

    def validation_success(self, instance_path):
        return self._simple_msg(path=instance_path, type='SUCCESS') + '\n\n'


@attr.s
class _PlainFormatter(object):

    _error_format = attr.ib()

    def filenotfound_error(self, path, exc_info):
        return "{!r} does not exist.\n".format(path)

    def parsing_error(self, path, exc_info):
        return "Failed to parse {}: {}\n".format(
            "<stdin>" if path == "<stdin>" else repr(path),
            exc_info[1],
        )

    def validation_error(self, instance_path, error):
        return self._error_format.format(file_name=instance_path, error=error)

    def validation_success(self, instance_path):
        return ""


def _namedAnyWithDefault(name):
    if "." not in name:
        name = "jsonschema." + name
    return namedAny(name)


parser = argparse.ArgumentParser(
    description="JSON Schema Validation CLI",
)
parser.add_argument(
    "-i", "--instance",
    action="append",
    dest="instances",
    help="""
        a path to a JSON instance (i.e. filename.json) to validate (may
        be specified multiple times). If no instances are provided via this
        option, one will be expected on standard input.
    """,
)
parser.add_argument(
    "-F", "--error-format",
    help="""
        the format to use for each validation error message, specified
        in a form suitable for str.format. This string will be passed
        one formatted object named 'error' for each ValidationError.
        Only provide this option when using --output=plain, which is the
        default. If this argument is unprovided and --output=plain is
        used, a simple default representation will be used."
    """,
)
parser.add_argument(
    "-o", "--output",
    choices=["plain", "pretty"],
    default="plain",
    help="""
        an output format to use. 'plain' (default) will produce minimal
        text with one line for each error, while 'pretty' will produce
        more detailed human-readable output on multiple lines.
    """,
)
parser.add_argument(
    "-V", "--validator",
    type=_namedAnyWithDefault,
    help="""
        the fully qualified object name of a validator to use, or, for
        validators that are registered with jsonschema, simply the name
        of the class.
    """,
)
parser.add_argument(
    "--version",
    action="version",
    version=__version__,
)
parser.add_argument(
    "schema",
    help="the path to a JSON Schema to validate with (i.e. schema.json)",
)


def parse_args(args):
    arguments = vars(parser.parse_args(args=args or ["--help"]))
    if arguments["validator"] is None:
        arguments["validator"] = validator_for(arguments["schema"])
    if arguments["output"] != "plain" and arguments["error_format"]:
        raise parser.error(
            "--error-format can only be used with --output plain"
        )
    if arguments["output"] == "plain" and arguments["error_format"] is None:
        arguments["error_format"] = "{error.instance}: {error.message}\n"
    return arguments


def _validate_instance(instance_path, instance, validator, outputter):
    invalid = False
    for error in validator.iter_errors(instance):
        invalid = True
        outputter.validation_error(instance_path=instance_path, error=error)

    if not invalid:
        outputter.validation_success(instance_path=instance_path)
    return invalid


def main(args=sys.argv[1:]):
    sys.exit(run(arguments=parse_args(args=args)))


def run(arguments, stdout=sys.stdout, stderr=sys.stderr, stdin=sys.stdin):
    outputter = _Outputter.from_arguments(
        arguments=arguments,
        stdout=stdout,
        stderr=stderr,
    )

    try:
        schema = outputter.load(arguments["schema"])
    except _CannotLoadFile:
        return 1

    try:
        arguments["validator"].check_schema(schema)
    except SchemaError as error:
        outputter.validation_error(
            instance_path=arguments["schema"],
            error=error,
        )
        return 1

    if arguments["instances"]:
        load, instances = outputter.load, arguments["instances"]
    else:
        def load(_):
            try:
                return json.load(stdin)
            except JSONDecodeError:
                outputter.parsing_error(
                    path="<stdin>", exc_info=sys.exc_info(),
                )
                raise _CannotLoadFile()
        instances = ["<stdin>"]

    validator = arguments["validator"](schema)
    exit_code = 0
    for each in instances:
        try:
            instance = load(each)
        except _CannotLoadFile:
            exit_code = 1
        else:
            exit_code |= _validate_instance(
                instance_path=each,
                instance=instance,
                validator=validator,
                outputter=outputter,
            )

    return exit_code
