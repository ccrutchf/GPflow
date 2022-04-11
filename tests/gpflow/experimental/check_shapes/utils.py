# Copyright 2022 The GPflow Contributors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Utilities for testing the `check_shapes` library.
"""
import inspect
from dataclasses import dataclass
from typing import Optional, Union

from gpflow.experimental.check_shapes import Dimension, Shape, get_shape
from gpflow.experimental.check_shapes.argument_ref import (
    ArgumentRef,
    AttributeArgumentRef,
    IndexArgumentRef,
    RootArgumentRef,
)
from gpflow.experimental.check_shapes.error_contexts import ErrorContext, MessageBuilder
from gpflow.experimental.check_shapes.specs import (
    ParsedArgumentSpec,
    ParsedDimensionSpec,
    ParsedNoteSpec,
    ParsedShapeSpec,
    ParsedTensorSpec,
)


@dataclass(frozen=True)
class TestContext(ErrorContext):

    message: str = "Fake test error context."

    def print(self, builder: MessageBuilder) -> None:
        builder.add_line(self.message)


@dataclass(frozen=True)
class TestShaped:

    test_shape: Shape


@get_shape.register(TestShaped)
def get_test_shaped_shape(shaped: TestShaped, context: ErrorContext) -> Shape:
    return shaped.test_shape


def t_unk() -> TestShaped:
    """
    Creates an object with an unknown shape, for testing.
    """
    return TestShaped(None)


def t(*shape: Dimension) -> TestShaped:
    """
    Creates an object with the given shape, for testing.
    """
    return TestShaped(shape)


def make_argument_ref(argument_name: str, *refs: Union[int, str]) -> ArgumentRef:
    result: ArgumentRef = RootArgumentRef(argument_name)
    for ref in refs:
        if isinstance(ref, int):
            result = IndexArgumentRef(result, ref)
        else:
            result = AttributeArgumentRef(result, ref)
    return result


def make_note_spec(note: Union[ParsedNoteSpec, str, None]) -> Optional[ParsedNoteSpec]:
    if isinstance(note, ParsedNoteSpec):
        return note
    elif isinstance(note, str):
        return ParsedNoteSpec(note)
    else:
        assert note is None
        return None


@dataclass(frozen=True)
class varrank:
    name: Optional[str]


@dataclass(frozen=True)
class bc:
    inner: Union[int, str, varrank, None]


def make_shape_spec(*dims: Union[int, str, varrank, bc, None]) -> ParsedShapeSpec:
    shape = []
    for dim in dims:
        broadcastable = False
        if isinstance(dim, bc):
            broadcastable = True
            dim = dim.inner

        if isinstance(dim, int):
            shape.append(
                ParsedDimensionSpec(
                    constant=dim,
                    variable_name=None,
                    variable_rank=False,
                    broadcastable=broadcastable,
                )
            )
        elif dim is None or isinstance(dim, str):
            shape.append(
                ParsedDimensionSpec(
                    constant=None,
                    variable_name=dim,
                    variable_rank=False,
                    broadcastable=broadcastable,
                )
            )
        else:
            assert isinstance(dim, varrank)
            shape.append(
                ParsedDimensionSpec(
                    constant=None,
                    variable_name=dim.name,
                    variable_rank=True,
                    broadcastable=broadcastable,
                )
            )
    return ParsedShapeSpec(tuple(shape))


def make_tensor_spec(
    shape_spec: ParsedShapeSpec, note: Union[ParsedNoteSpec, str, None]
) -> ParsedTensorSpec:
    return ParsedTensorSpec(shape_spec, make_note_spec(note))


def make_arg_spec(
    argument_ref: ArgumentRef, shape_spec: ParsedShapeSpec, note: Union[ParsedNoteSpec, str, None]
) -> ParsedArgumentSpec:
    return ParsedArgumentSpec(argument_ref, make_tensor_spec(shape_spec, note))


def current_line() -> int:
    """
    Returns the line number of the line that called this function.
    """
    stack = inspect.stack()
    return stack[1].lineno