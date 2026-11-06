#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Built-in objective modules (R-22 short-name registry).

Built-ins are importable submodules so the set can grow without touching
pyproject.toml (DESIGN.md 6, 9); each entry is a callable ``f(x, ctx) -> float`` where
bigger is better (R-21, DESIGN.md 3 R-09 note).
"""

from .auto_attack import objective as auto_attack_objective

REGISTRY = {"auto_attack": auto_attack_objective}
