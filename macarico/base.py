from __future__ import division, generators, print_function

import torch
import torch.nn as nn
from torch.nn.parameter import Parameter

class Env(object):
    r"""An implementation of an environment; aka a search task or MDP.

    Args:
        n_actions: the number of unique actions available to a policy
                   in this Env (actions are numbered [0, n_actions))

    Must provide a `_run_episode(policy)` function that performs a
    complete run through this environment, acting according to
    `policy`.

    May optionally provide a `_rewind` function that some learning
    algorithms (e.g., LOLS) requires.
    """
    def __init__(self, n_actions):
        self._trajectory = []
        self.n_actions = n_actions
    
    def horizon(self):
        raise NotImplementedError('abstract')

    def run_episode(self, policy):
        policy.new_example()
        return self._run_episode(policy)

    def rewind(self):
        # TODO: we need to reset the dynamic features but not the static features
        self._rewind()
        
    def _run_episode(self, policy):
        raise NotImplementedError('abstract')
    
    def _rewind(self):
        raise NotImplementedError('abstract')
    
class Policy(nn.Module):
    r"""A `Policy` is any function that contains a `forward` function that
    maps states to actions."""
    def forward(self, state):
        raise NotImplementedError('abstract')

    def new_example(self):
        for module in self.modules():
            if isinstance(module, StaticFeatures) or isinstance(module, Actor):
                module._features = None
            elif module != self and hasattr(module, 'new_example') and callable(module.new_example):
                module.new_example()

                
class Learner(Policy):
    r"""A `Learner` behaves identically to a `Policy`, but does "stuff"
    internally to, eg., compute gradients through pytorch's `backward`
    procedure. Not all learning algorithms can be implemented this way
    (e.g., LOLS) but most can (DAgger, reinforce, etc.)."""
    def forward(self, state):
        raise NotImplementedError('abstract method not defined.')

class LearningAlg(object):
    def __call__(self, example):
        raise NotImplementedError('abstract method not defined.')
    
    
class StaticFeatures(nn.Module):
    r"""`StaticFeatures` are any function that map an `Env` to a
    tensor. The dimension of the feature representation tensor should
    be (1, N, `dim`), where `N` is the length of the input, and
    `dim()` returns the dimensionality.

    The `forward` function computes the features."""
    def __init__(self, dim):
        nn.Module.__init__(self)
        self.dim = dim
        self._current_env = None
        self._features = None

    # TODO allow minibatching
    def _forward(self, env):
        raise NotImplementedError('abstract')

    def forward(self, env):
        if self._features is None:
            self._features = self._forward(env)
        assert self._features is not None
        return self._features
    
class Actor(nn.Module):
    r"""An `Actor` is a module that computes features dynamically as a policy runs."""
    def __init__(self, dim, attention):
        nn.Module.__init__(self)
        self._current_env = None
        self._features = None

        self.dim = dim
        self.attention = nn.ModuleList(attention)
        self.t = None
        self.T = None
        self.n_actions = None

        for att in attention:
            if att.actor_dependent:
                att.set_actor(self)

    def reset(self, env):
        self.t = None
        self.T = env.horizon()
        self.n_actions = env.n_actions
        self._features = [None] * self.T
    
    def _forward(self, state, x):
        raise NotImplementedError('abstract')
        
    def hidden(self):
        raise NotImplementedError('abstract')
        
    def forward(self, env):
        if self._features is None:
            self.reset(env)
            
        self.t = len(env._trajectory)
        assert self._features is not None

        assert self.t >= 0, 'expect t>=0, bug?'
        assert self.t < self.T, ('%d=t < T=%d' % (self.t, self.T))
        assert self.t < len(self._features)
        
        if self._features[self.t] is not None:
            return self._features[self.t]
        
        assert self.t == 0 or self._features[self.t-1] is not None

        x = []
        for att in self.attention:
            x += att(env)

        self._features[self.t] = self._forward(env, x)
        self.t += 1
        return self._features[self.t-1]

class Loss(object):
    def __init__(self, name, corpus_level=False):
        self.name = name
        self.corpus_level = corpus_level
        self.count = 0
        self.total = 0

    def evaluate(self, truth, state):
        raise NotImplementedError('abstract')

    def reset(self):
        self.count = 0
        self.total = 0

    def __call__(self, truth, state):
        val = self.evaluate(truth, state)
        if self.corpus_level:
            self.total = val
            self.count = 1
        elif val is not None:
            self.total += val
            self.count += 1
        return self.get()

    def get(self):
        return self.total / self.count if self.count > 0 else 0
    
class Reference(object):
    r"""A `Reference` is a special type of `Policy` that may use the ground
    truth to provide supervision. In many algorithms the `Reference`
    is considered to be the oracle policy (e.g., DAgger), but for some
    it is enough that it is a "good" policy (e.g., LOLS). Some
    algorithms do not use a `Reference` (e.g., reinforce).

    All `Reference`s must provide a `__call__` function that maps
    states (represented as an `Env`) to actions (just like `Policy`s).

    Some Leaners also assume that the `Reference` can provide a
    function `set_min_costs_to_go` for efficiency purposes.
    `set_min_costs_to_go` takes a `state` and a `cost_vector` (of size
    `n_actions`), and must fill in the cost-to-go for all actions if
    this reference were followed until the end of time."""
    def __call__(self, state):
        raise NotImplementedError('abstract')
    
    def set_min_costs_to_go(self, state, cost_vector):
        # optional, but required by some learning algorithms (eg aggrevate)
        raise NotImplementedError('abstract')

class Attention(nn.Module):
    r""" It is usually the case that the `Features` one wants to compute
    are a function of only some part of the input at any given time
    step. FOr instance, in a sequence labeling task, one might only
    want to look at the `Features` of the word currently being
    labeled. Or in a machine translation task, one might want to have
    dynamic, differentiable softmax-style attention.

    For static `Attention`, the class must define its `arity`: the
    number of places that it looks (e.g., one in sequence labeling).
    """
    
    arity = 0   # int=number of attention targets; None=attention (vector of length |input|)
    actor_dependent = False

    def __init__(self, features):
        nn.Module.__init__(self)
        self.features = features
        self.dim = (self.arity or 1) * self.features.dim
    
    def forward(self, state):
        raise NotImplementedError('abstract')

    def set_actor(self, actor):
        raise NotImplementedError('abstract')
    
    def make_out_of_bounds(self):
        oob = Parameter(torch.Tensor(self.arity or 1, self.features.dim))
        oob.data.zero_()
        return oob

class Torch(nn.Module):
    def __init__(self, features, dim, layers):
        nn.Module.__init__(self)
        self.features = features
        self.dim = dim
        self.torch_layers = layers if isinstance(layers, nn.ModuleList) else \
                            nn.ModuleList(layers) if isinstance(layers, list) else \
                            nn.ModuleList([layers])

    def forward(self, x):
        x = self.features(x)
        for l in self.torch_layers:
            x = l(x)
        return x
