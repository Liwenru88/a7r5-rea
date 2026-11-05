"""联合候选事务的测试ABI；颜色后端仍由测试显式提供。"""
import ctypes as c
from pathlib import Path

from grid_support import Sample, Report, Progress
from joint_support import Recipe, Model, Options, Work, Fit
from test_native_slots import Preset
from test_native_persistence import Document

HOME = Path(__file__).resolve().parents[1]
ASSET_BYTES = 1943
SCHEMA = 0x314a4641


class Asset(c.Structure):
    _fields_ = [('base', c.c_uint32), ('model_sha256', c.c_uint8 * 32), ('recipe', Recipe),
                ('native_mode', c.c_uint32), ('native_tone', c.c_int16 * 3), ('native_seed', c.c_uint32 * 129),
                ('matrix_mode', c.c_uint32), ('sector_matrix', c.c_int16 * 288)]


class Color(c.Structure):
    _fields_ = [('target', c.c_float * 3), ('predicted', c.c_float * 3), ('group', c.c_uint32)]


class ReportWork(c.Structure):
    _fields_ = [('colors', Color * 4096), ('errors', c.c_float * 4096)]


class Candidate(c.Structure):
    _fields_ = [('initial', Preset), ('report', __import__('test_native_persistence').Report),
                ('fit', Fit), ('validation', Report), ('name_bytes', c.c_uint32),
                ('name', c.c_char * 64), ('image', c.c_uint8 * ASSET_BYTES)]


class ImportWork(c.Structure):
    _fields_ = [('fit', Work), ('recipe', Recipe), ('report', ReportWork), ('candidate', Candidate)]


class Request(c.Structure):
    _fields_ = [('source', c.c_void_p), ('source_bytes', c.c_size_t),
                ('name', c.c_void_p), ('name_bytes', c.c_size_t),
                ('model', c.POINTER(Model)), ('initial', Preset), ('seed', c.POINTER(Recipe)),
                ('training', c.POINTER(Sample)), ('training_count', c.c_size_t),
                ('validation', c.POINTER(Sample)), ('validation_count', c.c_size_t), ('options', Options)]


def bind(api):
    from joint_support import bind as joint_bind
    from test_native_persistence import Io, Buffers
    joint_bind(api)
    api.af_cube_eval.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p]
    api.af_joint_asset_encode.argtypes = [c.POINTER(Asset), c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    api.af_joint_asset_decode.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Asset)]
    api.af_joint_report.argtypes = [c.POINTER(Model), c.c_uint32, c.c_void_p,
        c.POINTER(Recipe), c.POINTER(Sample), c.c_size_t, c.POINTER(ReportWork), c.POINTER(Report), Progress, c.c_void_p]
    api.af_grid_color_report.argtypes = [c.POINTER(Color), c.c_size_t, c.c_void_p, c.POINTER(Report)]
    api.af_import_cube.argtypes = [c.POINTER(Request), c.c_void_p, c.c_size_t, c.POINTER(ImportWork),
                                  c.POINTER(Candidate), Progress, c.c_void_p]
    api.af_import_document.argtypes = [c.POINTER(Candidate), c.POINTER(Document)]
    api.af_import_asset.argtypes = [c.POINTER(Document), c.POINTER(Asset)]
    api.af_persist_rename.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(Io), c.POINTER(Buffers), c.c_void_p, c.c_size_t]
    api.af_persist_export.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(Io), c.POINTER(Buffers),
                                     c.c_int, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    for name in ('af_store_bytes', 'af_posix_bytes', 'af_catalog_bytes'):
        getattr(api, name).restype = c.c_size_t
    api.af_store_init.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_size_t]
    api.af_store_recover.argtypes = [c.c_void_p, c.POINTER(Io), c.POINTER(Buffers), c.c_int, c.POINTER(Document)]
    api.af_store_commit.argtypes = [c.c_void_p, c.POINTER(Io), c.POINTER(Buffers), c.POINTER(Document)]
    api.af_store_generation.argtypes = [c.c_void_p]; api.af_store_generation.restype = c.c_uint64
    api.af_posix_init.argtypes = [c.c_void_p, c.c_int, c.POINTER(Io)]
    api.af_posix_close.argtypes = [c.c_void_p]
    api.af_catalog_init.argtypes = [c.c_void_p]
    api.af_read.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.POINTER(Preset)]
    api.af_dirty.argtypes = [c.c_void_p, c.c_uint32]
    api.af_restore.argtypes = [c.c_void_p, c.c_uint32, c.c_int]
    api.af_ui_assign.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_int, c.POINTER(c.c_int)]
    args = [c.c_void_p, c.c_void_p, c.POINTER(Io), c.POINTER(Buffers)]
    api.af_persist_load.argtypes = args + [c.c_int]
    api.af_persist_replace.argtypes = args + [c.POINTER(Document), c.c_int]
    api.af_persist_save.argtypes = args
    api.af_persist_clear.argtypes = args
    api.af_persist_copy.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(Io), c.POINTER(Io),
                                   c.POINTER(Buffers), c.c_void_p, c.c_size_t, c.c_int]
    api.af_document_decode.argtypes = [c.c_void_p, c.c_size_t, c.c_uint32, c.POINTER(Document)]
    api.af_document_report_applies.argtypes = [c.POINTER(Document), c.POINTER(Preset)]
    return api
