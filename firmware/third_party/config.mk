#
# Copyright (c) 2026, BlackBerry Limited. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# check the host platform and build environment assuming not self hosted to start
BUILD_QNX_SELF_HOSTED :=

ifneq ("$(findstring qnx,$(MAKE_HOST))", "")
$(info Detected QNX host. Build for QNX self-hosted by default.)
BUILD_QNX := true
BUILD_QNX_SELF_HOSTED := true
else ifneq ("$(findstring linux,$(MAKE_HOST))", "")
$(info Detected Linux host.)
else ifeq ($(OS), Windows_NT)
$(info Detected Windows host.)
else
$(info Detected Unknown host.)
endif

# if we aren't on self hosted check if we are building for QNX or host
ifndef BUILD_QNX_SELF_HOSTED
ifeq ($(origin QNX_HOST), environment)
$(info Detected QNX SDP environment.  Build QNX cross-compile.)
BUILD_QNX := true
else
$(info QNX SDP environment not detected building for host.)
BUILD_QNX :=
endif
endif

# configure compiler and linker
ifdef BUILD_QNX
ifdef BUILD_QNX_SELF_HOSTED
CC = clang
CXX = clang++
else
CC = qcc -Vgcc_nto$(PLATFORM)
CXX = q++ -Vgcc_nto$(PLATFORM)_cxx
endif
endif

ifdef BUILD_QNX
LDFLAGS_exe = -o
ifdef BUILD_QNX_SELF_HOSTED
LDFLAGS_shared = -shared -o
LDFLAGS_static = rc
LD = $(CC)
LD_static = llvm-ar
LD_shared = $(CC)
else
LDFLAGS_shared = -shared -o
LDFLAGS_static = -static -a
LD = $(CC)
LD_static = $(CC)
LD_shared = $(CC)
endif
endif
