import pytest
from Bio import Alphabet
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature
from Bio.SeqRecord import SeqRecord
from crseek import annotators
from crseek import estimators
from crseek import utils
from test.test_evaluators import build_estimator


class TestAnnotateSingle(object):
    def test_basic(self):
        spacer = Seq('A' * 20, alphabet=Alphabet.generic_rna)
        seqR = SeqRecord(Seq('T' * 5 + 'A' * 20 + 'CGG' + 'T' * 40,
                             alphabet=Alphabet.generic_dna),
                         id='CheckSeq')

        mod = estimators.CFDEstimator.build_pipeline()

        seqR = annotators.annotate_grna_binding(spacer, seqR, mod, exhaustive=True)

        assert len(seqR.features) == 1
        feat = seqR.features[0]

        assert feat.location.start == 5
        assert feat.location.end == 28
        assert feat.location.strand == 1
        assert feat.qualifiers.get('spacer') == 'A' * 20
        assert feat.qualifiers.get('On Target Score') == 1

    @pytest.mark.skipif(utils._missing_casoffinder(), reason="Need CasOff installed")
    def test_basic_casoffinder(self):
        spacer = Seq('A' * 20, alphabet=Alphabet.generic_rna)
        seqR = SeqRecord(Seq('T' * 5 + 'A' * 20 + 'CGG' + 'T' * 40,
                             alphabet=Alphabet.generic_dna),
                         id='CheckSeq')

        mod = build_estimator()

        seqR = annotators.annotate_grna_binding(spacer, seqR, mod, exhaustive=False)

        assert len(seqR.features) == 1
        feat = seqR.features[0]

        assert feat.location.start == 5
        assert feat.location.end == 28
        assert feat.location.strand == 1
        assert feat.qualifiers.get('spacer') == 'A' * 20
        assert feat.qualifiers.get('On Target Score') == 1

    def test_basic_extra_quals(self):
        spacer = Seq('A' * 20, alphabet=Alphabet.generic_rna)
        seqR = SeqRecord(Seq('T' * 5 + 'A' * 20 + 'CGG' + 'T' * 40,
                             alphabet=Alphabet.generic_dna),
                         id='CheckSeq')

        mod = build_estimator()

        seqR = annotators.annotate_grna_binding(spacer, seqR, mod, exhaustive=True,
                                                extra_qualifiers={'Something': 'here'})

        assert len(seqR.features) == 1
        feat = seqR.features[0]

        assert feat.qualifiers.get('spacer') == 'A' * 20
        assert feat.qualifiers.get('On Target Score') == 1
        assert feat.qualifiers.get('Something') == 'here'

    def test_reverse(self):
        spacer = Seq('A' * 20, alphabet=Alphabet.generic_rna)
        seqR = SeqRecord(Seq('T' * 5 + 'A' * 20 + 'CGG' + 'T' * 40,
                             alphabet=Alphabet.generic_dna).reverse_complement(),
                         id='CheckSeq')
        mod = build_estimator()

        seqR = annotators.annotate_grna_binding(spacer, seqR, mod, exhaustive=True)

        assert len(seqR.features) == 1
        feat = seqR.features[0]

        assert feat.location.start == 40
        assert feat.location.end == 63
        assert feat.location.strand == -1
        assert feat.qualifiers.get('spacer') == 'A' * 20
        assert feat.qualifiers.get('On Target Score') == 1


class TestSeqFeature(object):
    def test_basic(self):
        feat = annotators._build_target_feature(12, 1, 'A' * 20)
        assert type(feat) == type(SeqFeature())
        assert feat.location.start == 12
        assert feat.location.end == 35
        assert feat.location.strand == 1

        assert feat.qualifiers.get('spacer', None) == 'A' * 20
        assert feat.qualifiers.get('On Target Score', None) == 1

    def test_reverse_strand(self):
        feat = annotators._build_target_feature(100, -1, 'A' * 20)
        assert type(feat) == type(SeqFeature())
        assert feat.location.start == 100
        assert feat.location.end == 123
        assert feat.location.strand == -1

        assert feat.qualifiers.get('spacer', None) == 'A' * 20
        assert feat.qualifiers.get('On Target Score', None) == 1

    def test_value_error_on_bad_strand(self):
        with pytest.raises(ValueError):
            annotators._build_target_feature(12, '-', 'A' * 20)

    def test_extra_quals_come_along(self):
        feat = annotators._build_target_feature(12, 1, 'A' * 20, extra_quals={'ExtraQual': 50})
        assert feat.qualifiers.get('ExtraQual', None) == 50
