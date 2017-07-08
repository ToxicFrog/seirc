# A dictionary that stores only the last lru_size entries.

from collections import OrderedDict

class LRUDict(OrderedDict):
  def __init__(self, lru_size, *args, **kwargs):
    OrderedDict.__init__(self, *args, **kwargs)
    self._lru_size = lru_size

  def __setitem__(self, key, val):
    if key in self:
      del self[key]
    OrderedDict.__setitem__(self, key, val)
    if len(self) > self._lru_size:
      self.popitem(last=False)
