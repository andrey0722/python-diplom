#!/usr/bin/env python
"""Command line shortcuts for project Docker Compose targets.

The module keeps Compose files and helper commands for each target in one
place, so development and deployment flows can share the same entry point.
"""

import argparse
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
import subprocess
import sys
from typing import Final

type CommandFunc = Callable[['Target', Sequence[str]], int]

EXTRA_ARGS_PLACEHOLDER: Final = '[args]'
KEYBOARD_INTERRUPT_EXIT_CODE: Final = 130
KEYBOARD_INTERRUPT_MESSAGE: Final = 'Interrupted by user.'


@dataclass(frozen=True)
class Target:
    """Docker Compose target configuration.

    Args:
        name (str): Target name used in the command line interface.
        compose_files (tuple[str, ...]): Docker Compose files for the target.
        detached (bool): Whether `up` commands should default to detached mode.
        commands (dict[str, CommandFunc]): Extra commands for the target.
    """

    name: str
    compose_files: tuple[str, ...]
    detached: bool = False
    commands: dict[str, CommandFunc] = field(default_factory=dict)

    @property
    def compose(self) -> list[str]:
        """Build the base Docker Compose command for this target.

        Returns:
            list[str]: Command prefix with all target Compose files.
        """
        command = ['docker', 'compose']
        for compose_file in self.compose_files:
            command.extend(['-f', compose_file])
        return command


def run(command: Sequence[str]) -> int:
    """Run a command and return its exit code.

    Args:
        command (Sequence[str]): Command and arguments to execute.

    Returns:
        int: Process exit code.
    """
    print_command(command)
    return subprocess.call(command)


def run_many(commands: Sequence[Sequence[str]]) -> int:
    """Run commands sequentially and stop at the first failure.

    Args:
        commands (Sequence[Sequence[str]]): Commands to execute.

    Returns:
        int: First non-zero exit code or 0 after all commands pass.
    """
    for command in commands:
        exit_code = run(command)
        if exit_code != 0:
            return exit_code
    return 0


def print_command(command: Sequence[str]) -> None:
    """Print a shell-like representation of the command being executed.

    Args:
        command (Sequence[str]): Command and arguments to print.
    """
    print('+', ' '.join(command), flush=True)


def cmd_up(target: Target, args: Sequence[str]) -> int:
    """Start services for the target.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    command = [*target.compose, 'up', *args]

    if target.detached and '-d' not in args and '--detach' not in args:
        command.append('-d')

    return run(command)


def cmd_build(target: Target, args: Sequence[str]) -> int:
    """Build images for the target.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'build', *args])


def cmd_up_build(target: Target, args: Sequence[str]) -> int:
    """Start services and rebuild images if necessary.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    command = [*target.compose, 'up', '--build', *args]

    if target.detached and '-d' not in args and '--detach' not in args:
        command.append('-d')

    return run(command)


def cmd_down(target: Target, args: Sequence[str]) -> int:
    """Stop and remove containers for the target.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'down', *args])


def cmd_restart(target: Target, args: Sequence[str]) -> int:
    """Restart the target by running down and up.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments for `up`.

    Returns:
        int: Process exit code.
    """
    return run_many(
        [
            [*target.compose, 'down'],
            [
                *target.compose,
                'up',
                '--build',
                *args,
                *(['-d'] if target.detached else []),
            ],
        ]
    )


def cmd_logs(target: Target, args: Sequence[str]) -> int:
    """Follow logs for the target.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'logs', '-f', *args])


def cmd_config(target: Target, args: Sequence[str]) -> int:
    """Print the resolved Docker Compose configuration.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'config', *args])


def cmd_ps(target: Target, args: Sequence[str]) -> int:
    """Show containers for the target.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'ps', *args])


def cmd_exec(target: Target, args: Sequence[str]) -> int:
    """Run Docker Compose exec with custom arguments.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Service and command arguments.

    Returns:
        int: Process exit code or 2 when arguments are missing.
    """
    if not args:
        print(
            'error: exec requires arguments, for example: exec backend sh',
            file=sys.stderr,
        )
        return 2

    return run([*target.compose, 'exec', *args])


def cmd_run(target: Target, args: Sequence[str]) -> int:
    """Run Docker Compose run --rm with custom arguments.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Service and command arguments.

    Returns:
        int: Process exit code or 2 when arguments are missing.
    """
    if not args:
        print(
            'error: run requires arguments, for example: run backend sh',
            file=sys.stderr,
        )
        return 2

    return run([*target.compose, 'run', '--rm', *args])


def cmd_manage(target: Target, args: Sequence[str]) -> int:
    """Run a Django manage.py command in the backend service.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Django management command arguments.

    Returns:
        int: Process exit code or 2 when arguments are missing.
    """
    if not args:
        print(
            'error: manage requires a Django management command',
            file=sys.stderr,
        )
        return 2

    return run(
        [
            *target.compose,
            'run',
            '--rm',
            'backend',
            'python',
            'manage.py',
            *args,
        ]
    )


def cmd_shell(target: Target, args: Sequence[str]) -> int:
    """Open a shell in the running backend container.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Optional shell executable.

    Returns:
        int: Process exit code.
    """
    shell = args[0] if args else 'sh'
    return run([*target.compose, 'exec', 'backend', shell])


def cmd_django_shell(target: Target, args: Sequence[str]) -> int:
    """Open Django shell through manage.py shell.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Django shell arguments.

    Returns:
        int: Process exit code.
    """
    return cmd_manage(target, ['shell', *args])


def cmd_migrate(target: Target, args: Sequence[str]) -> int:
    """Run the migrate one-shot service.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose run arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'run', '--rm', 'migrate', *args])


def cmd_collectstatic(target: Target, args: Sequence[str]) -> int:
    """Run the collectstatic one-shot service.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose run arguments.

    Returns:
        int: Process exit code.
    """
    return run([*target.compose, 'run', '--rm', 'collectstatic', *args])


def cmd_check(target: Target, args: Sequence[str]) -> int:
    """Run Django check.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Django check arguments.

    Returns:
        int: Process exit code.
    """
    return cmd_manage(target, ['check', *args])


def cmd_check_deploy(target: Target, args: Sequence[str]) -> int:
    """Run Django deployment checks.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Django deployment check arguments.

    Returns:
        int: Process exit code.
    """
    return cmd_manage(target, ['check', '--deploy', *args])


def cmd_deploy(target: Target, args: Sequence[str]) -> int:
    """Run a minimal deployment sequence.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Extra Docker Compose arguments for `up`.

    Returns:
        int: First non-zero exit code or 0 when deployment succeeds.
    """
    up_command = [*target.compose, 'up', '-d', *args]

    return run_many(
        [
            [*target.compose, 'build'],
            [*target.compose, 'run', '--rm', 'migrate'],
            [*target.compose, 'run', '--rm', 'collectstatic'],
            up_command,
        ]
    )


def cmd_dev_init(target: Target, args: Sequence[str]) -> int:  # noqa: ARG001
    """Initialize local development state.

    Args:
        target (Target): Selected Compose target.
        args (Sequence[str]): Unused command arguments.

    Returns:
        int: First non-zero exit code or 0 when initialization succeeds.
    """
    return run_many(
        [
            [*target.compose, 'run', '--rm', 'migrate'],
            [*target.compose, 'run', '--rm', 'collectstatic'],
            [*target.compose, 'run', '--rm', 'create_admin'],
            [
                *target.compose,
                'run',
                '--rm',
                'backend',
                'python',
                'manage.py',
                'check',
            ],
        ]
    )


COMMON_COMMANDS: Final[dict[str, CommandFunc]] = {
    'up': cmd_up,
    'build': cmd_build,
    'up-build': cmd_up_build,
    'down': cmd_down,
    'restart': cmd_restart,
    'logs': cmd_logs,
    'config': cmd_config,
    'ps': cmd_ps,
    'exec': cmd_exec,
    'run': cmd_run,
    'manage': cmd_manage,
    'shell': cmd_shell,
    'django-shell': cmd_django_shell,
    'migrate': cmd_migrate,
    'collectstatic': cmd_collectstatic,
    'check': cmd_check,
}

HELP_FLAGS: Final[frozenset[str]] = frozenset(('-h', '--help'))
LIST_COMMAND_DESCRIPTIONS: Final[dict[str, str]] = {
    'help': 'Show commands available for the selected target.',
    'list': 'Show commands available for the selected target.',
}
LIST_COMMANDS: Final[frozenset[str]] = frozenset(LIST_COMMAND_DESCRIPTIONS)


TARGETS: Final[dict[str, Target]] = {
    'dev': Target(
        name='dev',
        compose_files=(
            'docker-compose.yml',
            'docker-compose.dev.yml',
        ),
        detached=False,
        commands={
            'init': cmd_dev_init,
        },
    ),
    'prod': Target(
        name='prod',
        compose_files=('docker-compose.yml',),
        detached=True,
        commands={
            'deploy': cmd_deploy,
            'check-deploy': cmd_check_deploy,
        },
    ),
}


def get_commands(target: Target) -> dict[str, CommandFunc]:
    """Return commands available for the target.

    Args:
        target (Target): Selected Compose target.

    Returns:
        dict[str, CommandFunc]: Common commands merged with target commands.
    """
    return {
        **COMMON_COMMANDS,
        **target.commands,
    }


def get_command_summary(command: CommandFunc) -> str:
    """Return the first docstring line for a command function.

    Args:
        command (CommandFunc): Command function to describe.

    Returns:
        str: Short command description or an empty string.
    """
    docstring = command.__doc__
    if not docstring:
        return ''

    return docstring.strip().splitlines()[0]


def format_command(command: Sequence[str]) -> str:
    """Format command arguments as a shell-like command.

    Args:
        command (Sequence[str]): Command arguments to format.

    Returns:
        str: Shell-like command string.
    """
    return ' '.join(command)


def format_command_sequence(commands: Sequence[Sequence[str]]) -> str:
    """Format a command sequence as a shell-like command.

    Args:
        commands (Sequence[Sequence[str]]): Commands to format.

    Returns:
        str: Command sequence joined with shell `&&`.
    """
    return ' && '.join(format_command(command) for command in commands)


def get_command_equivalent(  # noqa: C901, PLR0911, PLR0912
    command_name: str,
    target: Target,
) -> str:
    """Return a short command equivalent for the selected target.

    Args:
        command_name (str): Command name to describe.
        target (Target): Selected Compose target.

    Returns:
        str: Shell-like command equivalent or an empty string.
    """
    compose = ['<compose>']
    detach_args = ['-d'] if target.detached else []

    match command_name:
        case 'up':
            return format_command(
                [*compose, 'up', *detach_args, EXTRA_ARGS_PLACEHOLDER]
            )
        case 'build':
            return format_command([*compose, 'build', EXTRA_ARGS_PLACEHOLDER])
        case 'up-build':
            return format_command(
                [
                    *compose,
                    'up',
                    '--build',
                    *detach_args,
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'down':
            return format_command([*compose, 'down', EXTRA_ARGS_PLACEHOLDER])
        case 'restart':
            return format_command_sequence(
                [
                    [*compose, 'down'],
                    [
                        *compose,
                        'up',
                        '--build',
                        *detach_args,
                        EXTRA_ARGS_PLACEHOLDER,
                    ],
                ]
            )
        case 'logs':
            return format_command(
                [*compose, 'logs', '-f', EXTRA_ARGS_PLACEHOLDER]
            )
        case 'config':
            return format_command([*compose, 'config', EXTRA_ARGS_PLACEHOLDER])
        case 'ps':
            return format_command([*compose, 'ps', EXTRA_ARGS_PLACEHOLDER])
        case 'exec':
            return format_command(
                [
                    *compose,
                    'exec',
                    '<service>',
                    '<command>',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'run':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    '<service>',
                    '<command>',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'manage':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    'backend',
                    'python',
                    'manage.py',
                    '<command>',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'shell':
            return format_command([*compose, 'exec', 'backend', '<shell=sh>'])
        case 'django-shell':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    'backend',
                    'python',
                    'manage.py',
                    'shell',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'migrate':
            return format_command(
                [*compose, 'run', '--rm', 'migrate', EXTRA_ARGS_PLACEHOLDER]
            )
        case 'collectstatic':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    'collectstatic',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'check':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    'backend',
                    'python',
                    'manage.py',
                    'check',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'check-deploy':
            return format_command(
                [
                    *compose,
                    'run',
                    '--rm',
                    'backend',
                    'python',
                    'manage.py',
                    'check',
                    '--deploy',
                    EXTRA_ARGS_PLACEHOLDER,
                ]
            )
        case 'deploy':
            return format_command_sequence(
                [
                    [*compose, 'build'],
                    [*compose, 'run', '--rm', 'migrate'],
                    [*compose, 'run', '--rm', 'collectstatic'],
                    [*compose, 'up', '-d', EXTRA_ARGS_PLACEHOLDER],
                ]
            )
        case 'init':
            return format_command_sequence(
                [
                    [*compose, 'run', '--rm', 'migrate'],
                    [*compose, 'run', '--rm', 'collectstatic'],
                    [*compose, 'run', '--rm', 'create_admin'],
                    [
                        *compose,
                        'run',
                        '--rm',
                        'backend',
                        'python',
                        'manage.py',
                        'check',
                    ],
                ]
            )
        case 'help' | 'list':
            return f'compose.py {target.name} --help'
        case _:
            return ''


def get_command_help(
    command_name: str, description: str, target: Target
) -> str:
    """Build a help line with a command description and equivalent.

    Args:
        command_name (str): Command name to describe.
        description (str): Human-readable command description.
        target (Target): Selected Compose target.

    Returns:
        str: Help text for the command list.
    """
    equivalent = get_command_equivalent(command_name, target)
    if not equivalent:
        return description

    return f'{description} Runs: {equivalent}'


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser.

    Returns:
        argparse.ArgumentParser: Parser for the command line interface.
    """
    parser = argparse.ArgumentParser(
        prog='compose.py',
        usage='%(prog)s [-h] <target> <command> [args ...]',
        description='Run project Docker Compose commands by target.',
        epilog='Run `compose.py <target> --help` to list target commands.',
        add_help=False,
    )

    parser.add_argument(
        '-h',
        '--help',
        action='store_true',
        help='Show this help message and exit.',
    )
    parser.add_argument(
        'target',
        nargs='?',
        choices=sorted(TARGETS),
        help='Target Compose configuration.',
    )
    parser.add_argument(
        'command',
        nargs='?',
        help='Command to run for the selected target.',
    )
    parser.add_argument(
        'args',
        nargs=argparse.REMAINDER,
        help='Additional arguments passed to the selected command.',
    )

    return parser


def build_target_parser(target: Target) -> argparse.ArgumentParser:
    """Build a help parser for commands available on a target.

    Args:
        target (Target): Selected Compose target.

    Returns:
        argparse.ArgumentParser: Parser that renders target command help.
    """
    compose_files = '\n'.join(
        f'  {compose_file}' for compose_file in target.compose_files
    )
    compose_command = format_command(target.compose)
    parser = argparse.ArgumentParser(
        prog=f'compose.py {target.name}',
        usage='%(prog)s <command> [args ...]',
        description=(
            f"Target '{target.name}' Compose files:\n"
            f'{compose_files}\n\n'
            f'Base command (<compose>):\n'
            f'  {compose_command}'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        metavar='<command>',
        title='available commands',
    )

    command_summaries = {
        command_name: get_command_summary(command)
        for command_name, command in get_commands(target).items()
    }
    command_summaries.update(LIST_COMMAND_DESCRIPTIONS)

    for command_name in sorted(command_summaries):
        subparsers.add_parser(
            command_name,
            help=get_command_help(
                command_name,
                command_summaries[command_name],
                target,
            ),
        )
    parser.epilog = (
        'Additional arguments after <command> are passed to the selected '
        'command.'
    )

    return parser


def print_available_commands(target: Target) -> None:
    """Print commands available for a target.

    Args:
        target (Target): Selected Compose target.
    """
    build_target_parser(target).print_help()


def print_requested_help(
    parser: argparse.ArgumentParser,
    argv: Sequence[str],
) -> bool:
    """Print global or target help when the user requested it.

    Args:
        parser (argparse.ArgumentParser): Parser used for global help/errors.
        argv (Sequence[str]): Command line arguments without executable name.

    Returns:
        bool: True when help was requested and printed.
    """
    if argv and argv[0] in HELP_FLAGS:
        parser.print_help()
        return True

    if len(argv) > 1 and argv[1] in HELP_FLAGS:
        target_name = argv[0]

        if target_name not in TARGETS:
            parser.parse_args([target_name])
            return True

        print_available_commands(TARGETS[target_name])
        return True

    return False


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv (Sequence[str] | None): Command line arguments without the
            executable name. Uses `sys.argv` when omitted.

    Returns:
        int: Process exit code.
    """
    try:
        parser = build_parser()
        argv = list(sys.argv[1:] if argv is None else argv)

        if print_requested_help(parser, argv):
            return 0

        namespace = parser.parse_args(argv)

        if namespace.help:
            if namespace.target is None:
                parser.print_help()
            else:
                print_available_commands(TARGETS[namespace.target])
            return 0

        if namespace.target is None:
            parser.error('the following arguments are required: target')

        if namespace.command is None:
            parser.error('the following arguments are required: command')

        target = TARGETS[namespace.target]
        commands = get_commands(target)

        command_name = namespace.command

        if command_name in LIST_COMMANDS:
            print_available_commands(target)
            return 0

        command = commands.get(command_name)

        if command is None:
            print(
                f"error: unknown command '{command_name}' "
                f"for target '{target.name}'",
                file=sys.stderr,
            )
            print_available_commands(target)
            return 2

        return command(target, namespace.args)

    except KeyboardInterrupt:
        print(KEYBOARD_INTERRUPT_MESSAGE, file=sys.stderr)
        return KEYBOARD_INTERRUPT_EXIT_CODE


if __name__ == '__main__':
    raise SystemExit(main())
