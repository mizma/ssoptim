#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Main CLI Setup and Entrypoint."""

from __future__ import absolute_import, division, print_function

import click

from .ssoptim import ssoptim as impl
from ssoptim import __version__

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ssoptim")
def cli():
    """ssoptim: Stella Sora party build optimization tool."""
    pass


@cli.command()
@click.option(
    "--verbose",
    "-v",
    count=True,
    help="output in verbose mode",
)
def optimize(**kwargs):
    """Optimize talent-level distribution for a fixed party."""
    impl.cmd(kwargs)
    pass


# Entry point
def main():
    """Main script."""
    cli()


if __name__ == "__main__":
    main()
