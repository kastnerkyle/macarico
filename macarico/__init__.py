import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

infinity = float('inf')

class Env(object):
    def run_episode(self, policy):
        pass


class Policy(object):
    def __call__(self, state, limit_actions=None):
        raise NotImplementedError('abstract')


class Features(object):
    def __init__(self, dim):
        self.dim = dim
    def forward(self, state):
        raise NotImplementedError('abstract method not defined.')


class LearningAlg(object):
    def __call__(self, state, limit_actions=None):
        raise NotImplementedError('abstract method not defined.')


class LinearPolicy(Policy, nn.Module):
    """Linear policy

    Notes:

    This policy can be trained with
    - policy gradient via `policy.stochastic().reinforce(reward)`

    - Cost-sensitive one-against-all linear regression (CSOAA) via
      `policy.forward(state, truth)`

    """

    def __init__(self, features, n_actions):
        nn.Module.__init__(self)
        # set up cost sensitive one-against-all
        # TODO make this generalizable
        self.n_actions = n_actions
        self._lts_csoaa_predict = nn.Linear(features.dim, n_actions)
        self._lts_loss_fn = torch.nn.MSELoss(size_average=False) # only sum, don't average
        self.features = features

    def __call__(self, state, limit_actions=None):
        return self.greedy(state, limit_actions)   # Run greedy!

    def sample(self, state, limit_actions=None):
        return self.stochastic(state, limit_actions).data[0,0]   # get an integer instead of pytorch.variable

    def stochastic(self, state, limit_actions=None, return_probs=False):
        # predict costs using csoaa model
        pred_costs = self._lts_csoaa_predict(self.features(state))
        if limit_actions is not None:
            for i in xrange(len(pred_costs)):
                if i not in limit_actions:
                    pred_costs[i] = infinity
        # return a soft-min sample (==softmax on negative costs)
        probs = F.softmax(-pred_costs)
        return probs if return_probs else probs.multinomial()

    def greedy(self, state, limit_actions=None):
        # predict costs using the csoaa model
        pred_costs = self._lts_csoaa_predict(self.features(state))
        if limit_actions is None:
            return pred_costs.data.numpy().argmin()
        else:
            best = None
            for i in limit_actions:
                if best is None or pred_costs[i] < pred_costs[best]:
                    best = i
            return best
        # return the argmin cost
        return pred_costs.data.numpy().argmin()

    def forward(self, state, truth, limit_actions=None):

        # TODO: It would be better (more general) take a cost vector as input.
        # TODO: don't ignore limit_actions
        
        # truth must be one of:
        #  - None: ignored
        #  - an int specifying the single true output (which gets cost zero, rest are cost one)
        #  - a list of ints specifying multiple true outputs (ala above)
        #  - a 1d torch tensor specifying the exact costs of every action

        pred_costs = self._lts_csoaa_predict(self.features(state))

        if isinstance(truth, int):
            truth = [truth]
        if isinstance(truth, list):
            truth0 = truth
            truth = torch.ones(pred_costs.size())
            for k in truth0:
                truth[0,k] = 0.
        if isinstance(truth, torch.FloatTensor):
            truth = Variable(truth, requires_grad=False)
            return self._lts_loss_fn(pred_costs, truth)

        raise ValueError('lts_objective got truth of invalid type (%s)'
                         'expecting int, list[int] or torch.FloatTensor'
                         % type(truth))
