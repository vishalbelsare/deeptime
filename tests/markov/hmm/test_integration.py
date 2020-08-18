import itertools

import numpy as np
import pytest

from sktime.markov import tools

import sktime
from sktime.markov.hmm import MaximumLikelihoodHMM
from sktime.markov.msm import MarkovStateModel


def permutation_matrices(n):
    for mat in itertools.permutations(np.eye(n)):
        yield np.stack(mat)


def pytest_generate_tests(metafunc):
    if "hmm_scenario" in metafunc.fixturenames:
        metafunc.parametrize("hmm_scenario", list(itertools.product(
            [True, False],
            ["random", "pcca"],
            [1]
        )), indirect=True, ids=lambda x: f"reversible={x[0]},init_strategy={x[1]},lagtime={x[2]}")


class HMMScenario(object):

    def __init__(self, reversible: bool, init_strategy: str, lagtime: int):
        self.reversible = reversible
        self.init_strategy = init_strategy
        self.lagtime = lagtime

        self.n_steps = int(1e5)
        self.msm = MarkovStateModel(np.array([[0.7, 0.2, 0.1],
                                              [0.1, 0.8, 0.1],
                                              [0.1, 0.2, 0.7]]))
        self.hidden_stationary_distribution = tools.analysis.stationary_distribution(self.msm.transition_matrix)
        self.n_hidden = self.msm.n_states
        n_obs_per_hidden_state = 5
        self.n_observable = self.n_hidden * n_obs_per_hidden_state

        def gaussian(x, mu, sigma):
            prop = 1 / np.sqrt(2. * np.pi * sigma ** 2) * np.exp(- (x - mu) ** 2 / (2 * sigma ** 2))
            return prop / prop.sum()

        self.observed_alphabet = np.arange(self.n_observable)
        self.output_probabilities = np.array([gaussian(self.observed_alphabet, mu, 2.) for mu in
                                              np.arange((n_obs_per_hidden_state - 1) // 2,
                                                        self.n_observable, n_obs_per_hidden_state)])

        self.hidden_state_traj = self.msm.simulate(self.n_steps, 0)
        self.observable_state_traj = np.zeros_like(self.hidden_state_traj) - 1
        for state in range(self.n_hidden):
            ix = np.where(self.hidden_state_traj == state)[0]
            self.observable_state_traj[ix] = np.random.choice(self.n_observable,
                                                              p=self.output_probabilities[state],
                                                              size=ix.shape[0])
        assert -1 not in np.unique(self.observable_state_traj)

        if init_strategy == 'random':
            self.init_hmm = sktime.markov.hmm.init.discrete.random_guess(
                n_observation_states=self.n_observable, n_hidden_states=self.n_hidden, seed=17
            )
        elif init_strategy == 'pcca':
            self.init_hmm = sktime.markov.hmm.init.discrete.metastable_from_data(
                self.observable_state_traj, n_hidden_states=self.n_hidden, lagtime=self.lagtime
            )
        else:
            raise ValueError("unknown init strategy {}".format(init_strategy))
        self.hmm = MaximumLikelihoodHMM(self.init_hmm, reversible=self.reversible,
                                        lagtime=self.lagtime).fit(self.observable_state_traj).fetch_model()


scenario_map = dict()


@pytest.fixture
def hmm_scenario(request):
    if request.param in scenario_map.keys():
        return scenario_map[request.param]
    else:
        reversible, init_strategy, lagtime = request.param
        scenario = HMMScenario(reversible, init_strategy, lagtime)
        scenario_map[request.param] = scenario
        return scenario


def test_observation_probabilities(hmm_scenario):
    minerr = 1e6
    for perm in itertools.permutations(range(hmm_scenario.n_hidden)):
        err = np.max(np.abs(hmm_scenario.output_probabilities[np.array(perm)] -
                            hmm_scenario.hmm.output_probabilities))
        minerr = min(minerr, err)
    np.testing.assert_almost_equal(minerr, 0, decimal=2)


def test_stationary_distribution(hmm_scenario):
    model = hmm_scenario.hmm
    minerr = 1e6
    for perm in itertools.permutations(range(hmm_scenario.n_hidden)):
        minerr = min(minerr, np.max(np.abs(model.transition_model.stationary_distribution[np.array(perm)] -
                                           hmm_scenario.hidden_stationary_distribution)))
    np.testing.assert_almost_equal(minerr, 0, decimal=2)


def test_hidden_transition_matrix(hmm_scenario):
    model = hmm_scenario.hmm
    minerr = 1e6
    for perm in permutation_matrices(hmm_scenario.n_hidden):
        minerr = min(minerr, np.max(np.abs(perm.T @ model.transition_model.transition_matrix @ perm -
                                           hmm_scenario.msm.transition_matrix)))
    np.testing.assert_almost_equal(minerr, 0, decimal=1)


def test_hidden_path(hmm_scenario):
    model = hmm_scenario.hmm
    minerr = 1e6
    for perm in itertools.permutations(range(hmm_scenario.n_hidden)):
        viterbi_est = model.compute_viterbi_paths([hmm_scenario.observable_state_traj])[0]
        minerr = min(minerr, (np.array(perm)[viterbi_est] != hmm_scenario.hidden_state_traj).sum()
                     / hmm_scenario.n_steps)

    np.testing.assert_almost_equal(minerr, 0, decimal=1)
