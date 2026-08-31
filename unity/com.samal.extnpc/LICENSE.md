# Licence

Copyright 2026 Murathan Sam Ertem

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this package except in compliance with the License. You may obtain a copy of
the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

The full text ships with the engine repository as `LICENSE`, and the
attribution notices are in `NOTICE` beside it.

## What this package contains

Only the viewer: C# that reads a world bundle and renders it. It performs no
biology, draws no random numbers and derives no phenotype, so it carries no
third-party code and no asset with terms of its own.

The bodies it displays are baked elsewhere, through MPFB2, whose code is GPLv3
and is never vendored into this package. MPFB2's assets are CC0, so a mesh you
bake and ship in a game carries no copyleft obligation. That separation is the
reason the bake path lives outside this package rather than inside it.
