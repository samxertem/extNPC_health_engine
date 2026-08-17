using System.Runtime.CompilerServices;

// The test assembly may reach the runtime's internals.
//
// WHY NOT JUST MAKE THEM PUBLIC. HumanMesh.Bake and HumanMesh.Normalise are
// implementation: a consumer of this package installs a body asset and gets
// villagers, and never needs to flatten a hierarchy or rescale a mesh by hand.
// Widening the public API to make a test compile is how a package ends up
// unable to change anything without a major version, so the seam moves instead
// of the surface.
//
// Naming an assembly that does not exist in a build without tests is harmless:
// ExtNPC.Tests is Editor-only and constrained to UNITY_INCLUDE_TESTS, and
// InternalsVisibleTo to an absent assembly is simply never matched.
[assembly: InternalsVisibleTo("ExtNPC.Tests")]
