"""Structured launch requirements shared by the worker and the setup sheet."""


class LaunchRequirement(ValueError):
    def __init__(self, kind, message, **fields):
        super().__init__(message)
        self.guide = dict(kind=kind, message=message, **fields)


def require_package(store, game):
    try:
        return store.require_package(game)
    except ValueError as error:
        raise LaunchRequirement('packageUnavailable', str(error)) from error


def require_startup_checks(game, checks):
    approved = set(game.get('allowedStartupChecks', []))
    pending = [check for check in checks if check['url'] not in approved]
    if pending:
        raise LaunchRequirement('startupChecks', '此 HDD 需要你允许以下启动检查。', checks=pending)
