from __future__ import division
import os
from itertools import product
import numpy as np
import yaml
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Alphabet import IUPAC
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.pipeline import Pipeline
from crseek.preprocessing import MatchingTransformer, OneHotTransformer
from crseek import loaders

this_dir, this_filename = os.path.split(os.path.abspath(__file__))
DATA_PATH = os.path.join(this_dir, '..', "data")


class SequenceBase(BaseEstimator, ClassifierMixin):
    PAM = ''

    @staticmethod
    def build_pipeline(**kwargs):
        raise NotImplementedError

    def annotate_sequence(self, spacer, seq, mismatch_tolerance=4,
                          exhaustive=False, extra_qualifiers=None):
        """
        Parameters
        ----------
        spacer : Seq
            spacer to search
        seq : SeqRecord
            The sequence to query.
        exhaustive : bool
            If True then all positions within the seq_record are checked.
            If False then a mismatch search is performed first.
        mismatch_tolerance : int
            The number of mismatches to allow if using cas-offinder
        extra_qualifiers : dict
            Extra qualifiers to add to the SeqFeature

        Returns
        -------
        SeqRecord
            An shallow-copy of the original SeqRecord with the SeqFeatures
            filled with hits.
        """
        from crseek.annotators import annotate_grna_binding

        return annotate_grna_binding(spacer, seq, self,
                                     exhaustive=exhaustive,
                                     mismatch_tolerance=mismatch_tolerance,
                                     extra_qualifiers=extra_qualifiers)

    def predict(self, X):
        raise NotImplementedError


class MismatchEstimator(SequenceBase):
    """
    This estimator implements a simple "number of mismatches" determination of
    binding.
    """

    def __init__(self, seed_len=4, miss_seed=0,
                 miss_tail=2, miss_non_seed=3,
                 require_pam=True, pam='NRG'):
        """

        Parameters
        ----------
        seed_len : int
            The length of the seed region.
        tail_len : int
            The length of the tail region.
        miss_seed : int
            The number of mismatches allowed in the seed region.
        miss_tail : int
            The number of mismatches allowed in the tail region.
        pam : str
            Must the PAM be present
        pam : str
            Specific PAM

        Returns
        -------
        MismatchEstimator
        """

        self.seed_len = seed_len
        self.miss_seed = miss_seed
        self.miss_non_seed = miss_non_seed
        self.miss_tail = miss_tail
        self.require_pam = require_pam
        self.pam = pam

    @property
    def tail_len(self):
        return 20 - self.seed_len

    @staticmethod
    def load_yaml(path):

        with open(path) as handle:
            data = yaml.load(handle)

        kwargs = {'seed_len': data.get('Seed Length', 4),
                  'miss_seed': data.get('Seed Misses', 0),
                  'miss_non_seed': data.get('NonSeed Misses', 2),
                  'miss_tail': data.get('Tail Misses', 3),
                  'pam': data.get('PAM', 'NRG')}

        return MismatchEstimator.build_pipeline(**kwargs)

    @staticmethod
    def build_pipeline(**kwargs):
        """ Utility function to build a pipeline.
        Parameters
        ----------
        Keyword arguements are passed to the Estimator on __init__

        Returns
        -------

        Pipeline

        """

        pipe = Pipeline(steps=[('transform', MatchingTransformer(spacer_length = kwargs.pop('spacer_length', 20),
                                                                 pam = kwargs.pop('pam', 'NRG'))),
                               ('predict', MismatchEstimator(**kwargs))])
        pipe.matcher = pipe.steps[1][1]

        return pipe

    def fit(self, X, y=None):
        return self

    def predict(self, X):
        """

        Parameters
        ----------
        X : array
            Should be Nx21 as produced by preprocessing.MatchingTransformer
        Returns
        -------

        """

        if X.shape[1] != 21:
            raise ValueError('Input array shape must be Nx21')

        seed_miss = (X[:, -(self.seed_len + 1):-1] == False).sum(axis=1)
        non_seed_miss = (X[:, :-(self.seed_len)] == False).sum(axis=1)

        binders = (seed_miss <= self.miss_seed) & (non_seed_miss <= self.miss_tail)
        if self.pam:
            binders &= X[:, -1]

        return binders

    def predict_proba(self, X):
        return self.predict(X)


class MITEstimator(SequenceBase):
    def __init__(self, dampen=False, cutoff=0.75, PAM='NGG'):
        """
        Parameters
        ----------
        cutoff : float
            Cutoff for calling binding
        PAM : str
            Specific PAM

        Returns
        -------

        MITEstimator

        """
        self.cutoff = cutoff
        self.dampen = dampen
        self.penalties = np.array([0, 0, 0.014, 0, 0, 0.395, 0.317, 0,
                                   0.389, 0.079, 0.445, 0.508, 0.613,
                                   0.851, 0.732, 0.828, 0.615, 0.804,
                                   0.685, 0.583])
        self.PAM = PAM

    @staticmethod
    def build_pipeline(**kwargs):
        """ Utility function to build a pipeline.
        Parameters
        ----------
        Keyword arguements are passed to the Estimator on __init__

        Returns
        -------

        Pipeline

        """

        pipe = Pipeline(steps=[('transform', MatchingTransformer()),
                               ('predict', MITEstimator(**kwargs))])
        return pipe

    def fit(self, X, y=None):
        return self

    def predict(self, X):
        S = self.predict_proba(X)
        return S >= self.cutoff

    def predict_proba(self, X):
        """
        Parameters
        ----------
        X : np.array

        Returns
        -------
        np.array
            return score array S calculated based on MIT matrix, Nx1 vector

        """

        if X.shape[1] != 21:
            raise ValueError('Input array shape must be Nx21')

        s1 = (1 - (X[:, :-1] == np.array([False])) * self.penalties).prod(axis=1)

        mm = (X[:, :-1] == np.array([False])).sum(axis=1)
        n = mm.copy()

        def distance(x):
            idx = np.where(x == False)
            if len(idx[0]) > 1:
                return (idx[0][-1] - idx[0][0])
            else:
                return 0

        d = np.apply_along_axis(distance, axis=1, arr=X[:, :-1])
        with np.errstate(divide='ignore', invalid='ignore'):
            d = np.true_divide(d, (n - 1))
            d[d == np.inf] = 0
            d = np.nan_to_num(d)

        D = 1 / ((19 - d) / 19 * 4 + 1)
        D[n < 2] = 1
        S = s1
        psudoN = n.copy()
        psudoN[n < 1] = 1
        if self.dampen:
            S = s1 * D * (np.array([1]) / psudoN ** 2)

        S[mm == 0] = 1
        S *= X[:, -1].astype(float)

        return np.array(S)


class CFDEstimator(SequenceBase):
    def __init__(self, cutoff=0.75, PAM='NGG', matrix='CFD', strict=True):
        """
        Parameters
        ----------
        cutoff : float
            Cutoff for calling binding
        PAM : str
            PAM to use
        Returns
        -------

        CFDEstimator

        """

        self.cutoff = cutoff
        self._read_scores(matrix, strict)
        self.strict = strict
        self.PAM = PAM

    def _read_scores(self, matrix, strict):
        """ Reads in matrix and formats non-strictness
        Parameters
        ----------
        matrix : str or pd.DataFrame
        strict : bool

        """

        missmatch_encoding, pam_encoding = loaders.load_mismatch_scores(matrix)

        if not strict:
            degen = {'M': 'AC', 'R': 'AG', 'W': 'AT',
                     'S': 'CG', 'Y': 'CT', 'K': 'GT',
                     'V': 'ACG', 'H': 'ACT', 'D': 'AGT', 'B': 'CGT',
                     'N': 'ACGT'}

            for dest_target, target_cols in degen.items():
                for spacer_col in 'ACGU':
                    dest_col = spacer_col + dest_target
                    mean_cols = [spacer_col + tg for tg in target_cols]
                    missmatch_encoding[dest_col] = missmatch_encoding.loc[:, mean_cols].mean(axis=1)
            for pos2, pos3 in product(list(degen.keys()) + list('ACGT'), repeat=2):
                wanted_cols = [a + b for a, b in product(degen.get(pos2, pos2), degen.get(pos3, pos3))]
                pam_encoding[pos2 + pos3] = pam_encoding[wanted_cols].mean()

            missmatch_encoding = missmatch_encoding.reindex(columns=sorted(missmatch_encoding.columns))
            pam_encoding = pam_encoding.reindex(sorted(pam_encoding.index))

        self.score_vector = np.concatenate([missmatch_encoding.values.flatten(),
                                            pam_encoding.values.flatten()])

    @staticmethod
    def build_pipeline(**kwargs):
        """ Utility function to build a pipeline.
        Parameters
        ----------
        Keyword arguements are passed to the Estimator on __init__

        Returns
        -------

        Pipeline

        """
        strict = kwargs.get('strict', True)

        if strict:
            spacer_alpha, target_alpha = IUPAC.unambiguous_rna, IUPAC.unambiguous_dna
        else:
            spacer_alpha, target_alpha = IUPAC.unambiguous_rna, IUPAC.ambiguous_dna

        pipe = Pipeline(steps=[('transform', OneHotTransformer(target_alphabet=target_alpha,
                                                               spacer_alphabet=spacer_alpha)),
                               ('predict', CFDEstimator(**kwargs))])
        return pipe

    def fit(self, X, y=None):
        return self

    def predict(self, X):
        return self.predict_proba(X) >= self.cutoff

    def predict_proba(self, X):

        self._read_scores('CFD', strict=self.strict)

        if X.shape[1] != self.score_vector.shape[0]:
            raise ValueError('Input array shape must match self.score_vector')

        items = X.shape[0]
        scores = np.tile(self.score_vector, (items, 1))
        hot_scores = scores[X].reshape(-1, 21)

        probs = np.prod(hot_scores, axis=1)
        return probs


class KineticEstimator(BaseEstimator):
    def __init__(self, nseed=11, dC=1.8, Pmax=0.74, variant=None,
                 dI=None, npair=None, pam='NGG', cutoff=0.5):
        """
        Parameters
        ----------
        nseed : int
            Position at which half of single-missmatches will fail to cleave their target
        dC : float
            Free energy associated with a correct binding pair.
        Pmax : float
            The maximal cleavage efficiency of any single missmatch target
        variant : str
            Name of variant described in the paper. Must be:
             {spCas9,LbCpf1, AsCpf1}
             Sets all appropriate constants
        dI : float
            Free energy gain associated with an incorrect binding pair.
            Currently unused.
        npair : int
            Allowable distance between missmathes. Currently unused.
        pam : str
            PAM sequence.
        cutoff : float
            Probability cutoff to use when making binary comparisons.

        Returns
        -------

        KineticEstimator

        """

        if variant is not None:
            # Values taken from Figure 6: https://doi.org/10.1016/j.celrep.2018.01.045
            # Klein et al, Cell Reports, Feb 2018
            knowns = {'spCas9': {'nseed': 11, 'dC': 1.8, 'Pmax': 0.74, 'pam': 'NGG'},
                      'LbCpf1': {'nseed': 19, 'dC': 2.1, 'Pmax': 0.83, 'pam': 'NGG'},
                      'AsCpf1': {'nseed': 19, 'dC': 4, 'Pmax': 0.83, 'pam': 'NGG'}}
            try:
                data = knowns[variant]
            except KeyError:
                msg = 'Variant must be one of {spCas9,LbCpf1, AsCpf1} got: %s' % variant
                raise ValueError(msg)

            self.nseed = data['nseed']
            self.dC = data['dC']
            self.Pmax = data['Pmax']
            self.pam = data['pam']

        else:
            self.nseed = nseed
            self.dC = dC
            self.Pmax = Pmax
            self.pam = pam

        self.cutoff = cutoff

    @staticmethod
    def build_pipeline(**kwargs):
        """ Utility function to build a pipeline.
        Parameters
        ----------
        Keyword arguements are passed to the Estimator on __init__

        Returns
        -------

        Pipeline

        """

        pipe = Pipeline(steps=[('transform', MatchingTransformer()),
                               ('predict', KineticEstimator(**kwargs))])
        return pipe

    def fit(self, X, y=None):
        return self

    def predict(self, X):

        return self.predict_proba(X) >= self.cutoff

    def predict_proba(self, X):

        if X.shape[1] != 21:
            raise ValueError('Input array shape must be Nx21')

        # Input array  : Position 0 => PAM distal region
        # Klein model  : Position 0 => PAM proximal region

        pos = np.arange(20, 0, -1)
        pclv = self.Pmax / (1 + np.exp(-(pos - self.nseed) * self.dC))

        vals = pclv * (X[:, :-1] == False)

        scores = np.ones_like(vals)
        scores[X[:, :-1] == False] = vals[X[:, :-1] == False]

        probs = scores.prod(axis=1)

        # PAMs must be present
        probs *= X[:, -1]
        return probs
