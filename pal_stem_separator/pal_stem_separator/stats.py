import copy
import logging
from typing import Protocol, Self, Callable, Dict
import dataclasses
import json

class Semigroup[T](Protocol[T]):
    def mappend(self, other: T) -> T: ...

class Empty[T](Protocol[T]):
    @classmethod
    def mempty(cls) -> T: ...

class Monoid[T](Empty[T], Semigroup[T], Protocol[T]): ...

@dataclasses.dataclass
class Value[T]:
    value: T

    def get(self) -> T:
        return self.value

    def set(self, value: T) -> Self:
        x = copy.deepcopy(self)
        x.value = value
        return x

    def modify(self, f: Callable[[T], T]) -> Self:
        return self.set(f(self.value))

class Int(Value[int], Empty[int]):
    @classmethod
    def mempty(cls) -> Self:
        return cls(0)

class Float(Value[float], Empty[float]):
    @classmethod
    def mempty(cls) -> Self:
        return cls(0.0)

class Num[T: Int | Float](Value[T]):
    def __add__(self, other: Self) -> Self:
        return self.modify(lambda x: x.modify(lambda n: n + other.get().get()))

class IntSum(Value[int], Monoid[int]):
    @classmethod
    def mempty(cls) -> Self:
        return cls(0)
    def mappend(self, other: Self) -> Self:
        return self.modify(lambda n: n + other.get())

class FloatSum(Value[float], Monoid[float]):
    @classmethod
    def mempty(cls) -> Self:
        return cls(0.0)
    def mappend(self, other: Self) -> Self:
        return self.modify(lambda n: n + other.get())

class FloatLast(Value[float | None], Monoid[float | None]):
    @classmethod
    def mempty(cls) -> Self:
        return cls(None)
    def mappend(self, other: Self) -> Self:
        if other.get() is not None:
            return other
        return self

@dataclasses.dataclass
class StatsData:
    input_bytes: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    input_samples: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    input_secs: FloatSum = dataclasses.field(default_factory=lambda: FloatSum(0.0))

    processed_bytes: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    processed_samples: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    processed_secs: FloatSum = dataclasses.field(default_factory=lambda: FloatSum(0.0))

    output_bytes: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    output_samples: IntSum = dataclasses.field(default_factory=lambda: IntSum(0))
    output_secs: FloatSum = dataclasses.field(default_factory=lambda: FloatSum(0.0))

    latency_secs: FloatLast = dataclasses.field(default_factory=lambda: FloatLast(None))

class Stats(Value[StatsData], Monoid[StatsData]):
    @classmethod
    def create(cls, *args, **kwargs) -> Self:
        return cls(StatsData(*args, **kwargs))

    @classmethod
    def mempty(cls) -> Self:
        return cls(StatsData())

    def mappend(self, other: Self) -> Self:
        kwargs = {}
        for field in dataclasses.fields(self.get()):
            kwargs[field.name] = getattr(self.get(), field.name).mappend(getattr(other.get(), field.name))
        return self.set(StatsData(**kwargs))

    def save(self, args):
        with open(args.stats_path, 'w') as f:
            data = {}
            for field in dataclasses.fields(self.get()):
                data[field.name] = getattr(self.get(), field.name).get()
            json.dump(data, f)