// GENERATED FILE -- do not edit by hand.
//
// Produced by tests/test_unity_parity_fixture.py from the REAL
// formatters in dashboard/inspector.py. Every string here is what the
// dashboard drawer actually prints for the given input; 
// Tests/ParityFixtureTests.cs asserts InspectorFormat prints the same.
//
// Regenerate with EXTNPC_UPDATE_PARITY="<reason, >=12 chars>".
// recut_reason: cover exact binary midpoints after the half-to-even bug

namespace ExtNPC.Tests
{
    internal static class ParityFixture
    {
        internal struct Case
        {
            public string Fn;
            public float A;
            public float B;
            public string Expected;
        }

        internal static readonly Case[] Cases =
        {
            new Case { Fn = "FmtF", A = 0.0f, B = 0.0f, Expected = "0" },
            new Case { Fn = "RelationshipLabel", A = 0.0f, B = 0.0f, Expected = "outbred" },
            new Case { Fn = "FColor", A = 0.0f, B = 0.0f, Expected = "#ffffff" },
            new Case { Fn = "FmtF", A = 0.004f, B = 0.0f, Expected = "0.0040" },
            new Case { Fn = "RelationshipLabel", A = 0.004f, B = 0.0f, Expected = "distant kin" },
            new Case { Fn = "FColor", A = 0.004f, B = 0.0f, Expected = "#ffffff" },
            new Case { Fn = "FmtF", A = 0.015625f, B = 0.0f, Expected = "0.0156" },
            new Case { Fn = "RelationshipLabel", A = 0.015625f, B = 0.0f, Expected = "second cousins" },
            new Case { Fn = "FColor", A = 0.015625f, B = 0.0f, Expected = "#c98500" },
            new Case { Fn = "FmtF", A = 0.03125f, B = 0.0f, Expected = "0.0312" },
            new Case { Fn = "RelationshipLabel", A = 0.03125f, B = 0.0f, Expected = "first cousins once removed" },
            new Case { Fn = "FColor", A = 0.03125f, B = 0.0f, Expected = "#c98500" },
            new Case { Fn = "FmtF", A = 0.0625f, B = 0.0f, Expected = "0.0625" },
            new Case { Fn = "RelationshipLabel", A = 0.0625f, B = 0.0f, Expected = "first cousins" },
            new Case { Fn = "FColor", A = 0.0625f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "FmtF", A = 0.078125f, B = 0.0f, Expected = "0.0781" },
            new Case { Fn = "RelationshipLabel", A = 0.078125f, B = 0.0f, Expected = "first cousins" },
            new Case { Fn = "FColor", A = 0.078125f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "FmtF", A = 0.10938f, B = 0.0f, Expected = "0.1094" },
            new Case { Fn = "RelationshipLabel", A = 0.10938f, B = 0.0f, Expected = "first cousins" },
            new Case { Fn = "FColor", A = 0.10938f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "FmtF", A = 0.125f, B = 0.0f, Expected = "0.1250" },
            new Case { Fn = "RelationshipLabel", A = 0.125f, B = 0.0f, Expected = "uncle\u2013niece / double first cousin" },
            new Case { Fn = "FColor", A = 0.125f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "FmtF", A = 0.25f, B = 0.0f, Expected = "0.2500" },
            new Case { Fn = "RelationshipLabel", A = 0.25f, B = 0.0f, Expected = "full sib / parent\u2013offspring" },
            new Case { Fn = "FColor", A = 0.25f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "FmtF", A = 0.5f, B = 0.0f, Expected = "0.5000" },
            new Case { Fn = "RelationshipLabel", A = 0.5f, B = 0.0f, Expected = "full sib / parent\u2013offspring" },
            new Case { Fn = "FColor", A = 0.5f, B = 0.0f, Expected = "#d03b3b" },
            new Case { Fn = "Signed2", A = 0.0f, B = 0.0f, Expected = "+0.00" },
            new Case { Fn = "Signed2", A = 0.213f, B = 0.0f, Expected = "+0.21" },
            new Case { Fn = "Signed2", A = -0.213f, B = 0.0f, Expected = "-0.21" },
            new Case { Fn = "Signed2", A = 1.731f, B = 0.0f, Expected = "+1.73" },
            new Case { Fn = "Signed2", A = -0.687f, B = 0.0f, Expected = "-0.69" },
            new Case { Fn = "Signed2", A = 0.6f, B = 0.0f, Expected = "+0.60" },
            new Case { Fn = "Signed2", A = 0.61f, B = 0.0f, Expected = "+0.61" },
            new Case { Fn = "Fixed2", A = 0.0f, B = 0.0f, Expected = "0.00" },
            new Case { Fn = "Fixed2", A = 41.554f, B = 0.0f, Expected = "41.55" },
            new Case { Fn = "Fixed2", A = 4.6f, B = 0.0f, Expected = "4.60" },
            new Case { Fn = "Fixed2", A = 52.0f, B = 0.0f, Expected = "52.00" },
            new Case { Fn = "Fixed3", A = 0.9734f, B = 0.0f, Expected = "0.973" },
            new Case { Fn = "Fixed3", A = 0.9f, B = 0.0f, Expected = "0.900" },
            new Case { Fn = "Fixed3", A = 0.899f, B = 0.0f, Expected = "0.899" },
            new Case { Fn = "Fixed3", A = 1.071f, B = 0.0f, Expected = "1.071" },
            new Case { Fn = "Fixed3", A = 0.475f, B = 0.0f, Expected = "0.475" },
            new Case { Fn = "SignedYears", A = 0.0f, B = 0.0f, Expected = "+0.0 y" },
            new Case { Fn = "SignedYears", A = 1.24f, B = 0.0f, Expected = "+1.2 y" },
            new Case { Fn = "SignedYears", A = -1.24f, B = 0.0f, Expected = "-1.2 y" },
            new Case { Fn = "SignedYears", A = 3.0f, B = 0.0f, Expected = "+3.0 y" },
            new Case { Fn = "SignedYears", A = 3.1f, B = 0.0f, Expected = "+3.1 y" },
            new Case { Fn = "Percent0", A = 0.0f, B = 0.0f, Expected = "0%" },
            new Case { Fn = "Percent0", A = 0.125f, B = 0.0f, Expected = "12%" },
            new Case { Fn = "Percent0", A = 0.375f, B = 0.0f, Expected = "38%" },
            new Case { Fn = "Percent0", A = 0.625f, B = 0.0f, Expected = "62%" },
            new Case { Fn = "Percent0", A = 0.875f, B = 0.0f, Expected = "88%" },
            new Case { Fn = "Percent0", A = 0.005f, B = 0.0f, Expected = "0%" },
            new Case { Fn = "Percent0", A = 0.015f, B = 0.0f, Expected = "2%" },
            new Case { Fn = "Percent0", A = 0.167f, B = 0.0f, Expected = "17%" },
            new Case { Fn = "Percent0", A = 0.25f, B = 0.0f, Expected = "25%" },
            new Case { Fn = "Percent0", A = 0.5f, B = 0.0f, Expected = "50%" },
            new Case { Fn = "Percent0", A = 0.8734f, B = 0.0f, Expected = "87%" },
            new Case { Fn = "Percent0", A = 1.0f, B = 0.0f, Expected = "100%" },
            new Case { Fn = "Signed4", A = 0.0f, B = 0.0f, Expected = "+0.0000" },
            new Case { Fn = "Signed4", A = 0.07014f, B = 0.0f, Expected = "+0.0701" },
            new Case { Fn = "Signed4", A = -0.0123f, B = 0.0f, Expected = "-0.0123" },
            new Case { Fn = "Signed4", A = 0.25f, B = 0.0f, Expected = "+0.2500" },
            new Case { Fn = "StatureCost", A = -1.312f, B = 0.0f, Expected = "-1.31 cm" },
            new Case { Fn = "StatureCost", A = -0.75f, B = 0.0f, Expected = "-0.75 cm" },
            new Case { Fn = "StatureCost", A = -0.938f, B = 0.0f, Expected = "-0.94 cm" },
            new Case { Fn = "StatureCost", A = -0.4f, B = 0.0f, Expected = "-0.40 cm" },
            new Case { Fn = "Height", A = 168.34f, B = 0.0f, Expected = "168.3 cm" },
            new Case { Fn = "Height", A = 99.5f, B = 0.0f, Expected = "99.5 cm" },
            new Case { Fn = "Height", A = 180.0f, B = 0.0f, Expected = "180.0 cm" },
            new Case { Fn = "HeightLive", A = 112.4f, B = 171.2f, Expected = "112.4 cm  \u2192 171 adult" },
            new Case { Fn = "HeightLive", A = 171.2f, B = 171.2f, Expected = "171.2 cm" },
            new Case { Fn = "HeightLive", A = 171.2f, B = 171.23f, Expected = "171.2 cm" },
            new Case { Fn = "HeightLive", A = 168.34f, B = 168.34f, Expected = "168.3 cm" },
            new Case { Fn = "HeightLive", A = 99.5f, B = 180.4f, Expected = "99.5 cm  \u2192 180 adult" },
            new Case { Fn = "Bmi", A = 24.42f, B = 1.0f, Expected = "24.4 at maturity" },
            new Case { Fn = "Bmi", A = 24.42f, B = 0.0f, Expected = "24.4" },
            new Case { Fn = "Bmi", A = 15.6f, B = 1.0f, Expected = "15.6 at maturity" },
            new Case { Fn = "NormStress", A = -1.5f, B = 0.0f, Expected = "0.000000" },
            new Case { Fn = "NormStress", A = 2.5f, B = 0.0f, Expected = "1.000000" },
            new Case { Fn = "NormStress", A = 0.0f, B = 0.0f, Expected = "0.375000" },
            new Case { Fn = "NormStress", A = -9.0f, B = 0.0f, Expected = "0.000000" },
            new Case { Fn = "NormStress", A = 9.0f, B = 0.0f, Expected = "1.000000" },
            new Case { Fn = "NormStress", A = 0.213f, B = 0.0f, Expected = "0.428250" },
            new Case { Fn = "NormHeterozygosity", A = 0.0f, B = 0.0f, Expected = "0.000000" },
            new Case { Fn = "NormHeterozygosity", A = 0.412f, B = 0.0f, Expected = "0.686667" },
            new Case { Fn = "NormHeterozygosity", A = 0.6f, B = 0.0f, Expected = "1.000000" },
            new Case { Fn = "NormHeterozygosity", A = 0.9f, B = 0.0f, Expected = "1.000000" },
        };
    }
}
