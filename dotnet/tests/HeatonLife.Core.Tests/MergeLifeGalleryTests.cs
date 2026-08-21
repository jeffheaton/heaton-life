using System.Collections.Generic;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pins for the featured MergeLife rules (spec/mergelife.md "Featured rules").
    /// The catalog is a cross-implementation contract with no vector files behind
    /// it (like the built-in patterns), so the suite is what holds it: every rule
    /// must parse, already be canonical, and actually run; the presentation text
    /// must be present and unambiguous; and the order — which apps show — is part
    /// of the set. The mirror of python/tests/test_mergelife_gallery.py.
    /// </summary>
    public class MergeLifeGalleryTests
    {
        private const int GallerySize = 15;

        [Fact]
        public void GalleryMatchesTheSpecTable()
        {
            Assert.Equal(GallerySize, MergeLifeGallery.All.Length);
            // Entry 1 is the paper's rule and the family default; entry 2 is the
            // engineered sibling that must sit beside its parent.
            Assert.Equal("Red World (paper)", MergeLifeGallery.All[0].Name);
            Assert.Equal("e542-5f79-9341-f31e-6c6b-7f08-8773-7068", MergeLifeGallery.All[0].Rule);
            Assert.Equal("Cobalt Reef", MergeLifeGallery.All[1].Name);
            Assert.Equal("Mood Ring", MergeLifeGallery.All[GallerySize - 1].Name);
        }

        [Fact]
        public void TheDefaultRuleIsTheFirstEntry()
        {
            Assert.Equal(MergeLifeGallery.All[0].Rule, MergeLife.CanonicalRule(MergeLife.DefaultRule));
        }

        [Fact]
        public void EveryRuleIsValidAndAlreadyCanonical()
        {
            foreach (FeaturedRule entry in MergeLifeGallery.All)
            {
                Assert.Null(MergeLife.RuleError(entry.Rule));
                // The spec requires the stored form to be canonical, so a host can
                // compare a world's rule against the gallery without normalizing.
                Assert.Equal(entry.Rule, MergeLife.CanonicalRule(entry.Rule));
            }
        }

        [Fact]
        public void EveryEntryCarriesPresentationText()
        {
            foreach (FeaturedRule entry in MergeLifeGallery.All)
            {
                Assert.False(string.IsNullOrWhiteSpace(entry.Name));
                Assert.Equal(entry.Name.Trim(), entry.Name);
                Assert.False(string.IsNullOrWhiteSpace(entry.Description));
                Assert.Equal(entry.Description.Trim(), entry.Description);
                Assert.EndsWith(".", entry.Description);
            }
        }

        [Fact]
        public void RulesAndNamesAreUnique()
        {
            var rules = new HashSet<string>();
            var names = new HashSet<string>();
            foreach (FeaturedRule entry in MergeLifeGallery.All)
            {
                Assert.True(rules.Add(entry.Rule), $"duplicate rule: {entry.Rule}");
                Assert.True(names.Add(entry.Name), $"duplicate name: {entry.Name}");
            }
        }

        [Fact]
        public void CobaltReefIsAPermutationOfRedWorld()
        {
            // Its provenance claim in the spec: same octets, reordered.
            string[] red = MergeLifeGallery.All[0].Rule.Split('-');
            string[] cobalt = MergeLifeGallery.All[1].Rule.Split('-');
            System.Array.Sort(red);
            System.Array.Sort(cobalt);
            Assert.Equal(red, cobalt);
            Assert.NotEqual(MergeLifeGallery.All[0].Rule, MergeLifeGallery.All[1].Rule);
        }

        [Fact]
        public void EveryRuleActuallyRuns()
        {
            // A gallery entry that cannot drive a world is not a featured rule.
            var rgb = new byte[32 * 32 * 3];
            foreach (FeaturedRule entry in MergeLifeGallery.All)
            {
                var world = new MergeLife(entry.Rule, 32, 32);
                world.SeedSoup(7);
                world.Step(8);
                world.WriteFrame(rgb);
                Assert.Equal(8, world.Generation);
            }
        }
    }
}
