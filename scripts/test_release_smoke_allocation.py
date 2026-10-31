#!/usr/bin/env python3
"""Small-file controls for precharged allocation, without native tools or network."""
import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def load(name):
 spec=importlib.util.spec_from_file_location(name,HERE/'release_smoke'/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class AllocationTests(unittest.TestCase):
 def setUp(self):
  self.w=load('window');self.p=load('prepare');self.w.CAP=512*2**20
  self.clock=[100.0];self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.window=self.w.Window.admit(Path(self.tmp.name).resolve(),started=100,clock=lambda:self.clock[0],disk_usage=lambda _:SimpleNamespace(free=32*2**30))
  self.raw=b'exact archive bytes';self.digest=hashlib.sha256(self.raw).hexdigest()
 def padded_fstat(self,fd):
  info=self.real_fstat(fd)
  if stat.S_ISREG(info.st_mode) and info.st_size:
   return SimpleNamespace(st_mode=info.st_mode,st_size=info.st_size,st_blocks=2048,st_dev=info.st_dev,st_ino=info.st_ino)
  return info
 def test_old_allowance_rejects_allocation_overrun_and_retains_counters(self):
  self.window.reserve([('archive.zip','file',len(self.raw))]);self.real_fstat=self.w.os.fstat
  with patch.object(self.w.os,'fstat',self.padded_fstat),self.assertRaises(self.w.Rejected) as caught:
   self.window.copy(io.BytesIO(self.raw),'archive.zip',len(self.raw),self.digest)
  row=caught.exception.ledger_row
  self.assertEqual(row['logical'],len(self.raw));self.assertEqual(row['allocated'],2**20)
  self.assertGreater(row['allocated'],row['allocated_charge'])
  self.assertEqual(self.p.failure_detail(caught.exception)['ledger_row']['allocated'],2**20)
 def test_precharged_allowance_accepts_same_write_without_charge_growth(self):
  self.window.reserve([('archive.zip','file',len(self.raw))],allocation_limits={'archive.zip':2*2**20})
  before=self.window.entries['archive.zip']['allocated_charge'];self.real_fstat=self.w.os.fstat
  with patch.object(self.w.os,'fstat',self.padded_fstat):result=self.window.copy(io.BytesIO(self.raw),'archive.zip',len(self.raw),self.digest)
  self.assertEqual(result,{'bytes':len(self.raw),'sha256':self.digest})
  row=self.window.entries['archive.zip'];self.assertEqual(row['logical_charge'],len(self.raw));self.assertEqual(row['allocated_charge'],before)
 def test_actual_archive_policy_and_cumulative_cap(self):
  rows=[{'id':12812978203,'bytes':5324375},{'id':12813182338,'bytes':166109022}]
  limits=self.p.reserve_archives(self.window,rows)
  self.assertEqual(limits,{'12812978203.zip':16*2**20,'12813182338.zip':320*2**20})
  self.assertEqual(self.window.entries['12813182338.zip']['logical_charge'],166109022)
  self.assertLess(self.window.total('allocated_charge'),512*2**20)
  entries=dict(self.window.entries)
  with self.assertRaises(self.w.Rejected):self.window.reserve([('too-large.zip','file',1)],allocation_limits={'too-large.zip':512*2**20})
  self.assertEqual(self.window.entries,entries);self.assertFalse((Path(self.tmp.name).resolve()/'too-large.zip').exists())
 def test_exact_length_and_digest_still_required(self):
  for name,data,digest in [('long.zip',self.raw+b'x',self.digest),('hash.zip',self.raw,'0'*64)]:
   self.window.reserve([(name,'file',len(self.raw))],allocation_limits={name:2*2**20})
   with self.assertRaises(self.w.Rejected):self.window.copy(io.BytesIO(data),name,len(self.raw),digest)
 def test_identity_replacement_rejected(self):
  self.window.reserve([('archive.zip','file',len(self.raw))],allocation_limits={'archive.zip':2*2**20})
  self.window.copy(io.BytesIO(self.raw),'archive.zip',len(self.raw),self.digest)
  info=(Path(self.tmp.name).resolve()/'archive.zip').stat()
  replaced=SimpleNamespace(st_mode=info.st_mode,st_size=info.st_size,st_blocks=info.st_blocks,st_dev=info.st_dev,st_ino=info.st_ino+1)
  with self.assertRaises(self.w.Rejected):self.window.observe('archive.zip',replaced)
 def test_expired_window_cannot_reserve_or_write(self):
  self.window.reserve([('archive.zip','file',len(self.raw))],allocation_limits={'archive.zip':2*2**20})
  self.clock[0]=100+self.w.SECONDS
  with self.assertRaises(self.w.Rejected):self.window.copy(io.BytesIO(self.raw),'archive.zip',len(self.raw),self.digest)
  with self.assertRaises(self.w.Rejected):self.window.reserve([('late.zip','file',1)],allocation_limits={'late.zip':2*2**20})
  self.assertFalse((Path(self.tmp.name).resolve()/'archive.zip').exists())
 def test_unknown_or_small_allocation_ceiling_rejected(self):
  for limits in [{'other.zip':2**20},{'archive.zip':1}]:
   with self.assertRaises(self.w.Rejected):self.window.reserve([('archive.zip','file',len(self.raw))],allocation_limits=limits)
  self.assertNotIn('archive.zip',self.window.entries)

if __name__=='__main__':unittest.main()
