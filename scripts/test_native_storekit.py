"""Pure binding/admission controls for the one native payment command; no native/network."""
import plistlib,copy,sys
import contextlib,datetime as dt,hashlib,importlib.util,io,json,os,signal,subprocess,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
DRIVER=Path(__file__).with_name('check-native-storekit.py')
MODULES=ROOT/'scripts/release_smoke'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def jobs(now,elapsed=300):
    return {'total_count':1,'jobs':[{'id':7,'name':'Native StoreKit eight-case acceptance','run_id':123,'run_attempt':1,'head_sha':'a'*40,'status':'in_progress','runner_id':55,'runner_name':'fixture','labels':['macos-15'],'started_at':(now-dt.timedelta(seconds=elapsed)).isoformat()}]}

class NativeFailureProgressTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_failure_progress_test',DRIVER)
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.scope=Path(self.temporary.name)
        self.staging=self.scope/'result.xcresult/Staging/1_Test/Diagnostics'
        self.staging.mkdir(parents=True)
        self.run=SimpleNamespace(meta={'failures':[{'type':'original_failure'}],
            'native_failure_markers':{'inert_host_observed':False,
             'first_case_start_observed':None,'log_bytes_examined':1720}})
    def collect(self,check=lambda:None):
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('no native calls')):
            self.m.record_native_failure_progress(self.run,self.scope,check)
        self.assertEqual(self.run.meta['failures'],[{'type':'original_failure'}])
        return self.run.meta['native_failure_progress']
    def test_fixed_milestones_and_hashes_never_include_raw_path_or_launch_values(self):
        raw=('01:15:32.196 xcodebuild[50:60] Beginning test session Private-Session\n'
             '01:15:32.269 xcodebuild[50:60] Test runner session acquired connection.\n'
             '01:15:32.869 xcodebuild[50:60] UUID: Installing app at path: /private/SENSITIVE\n'
             '01:15:51.515 xcodebuild[50:60] UUID: Installed app at path: /private/SENSITIVE\n'
             '01:15:52.941 xcodebuild[50:60] UUID: Launching app with identifier: SECRET and options: {\n'
             ' environment = {TOKEN = SENSITIVE;}\n'
             '01:24:36.281 xcodebuild[50:60] UUID: Launched app with identifier: SECRET (pid = 123)\n').encode()
        (self.staging/'Session-synthetic.log').write_bytes(raw)
        result=self.collect();self.assertTrue(result['diagnostic_only'])
        self.assertEqual(result['stdout_markers']['first_case_start_observed'],None)
        record=result['sessions'][0]
        self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual([e['kind'] for e in record['milestones']],
            ['session_started','runner_connected','app_install_requested','app_installed','app_launch_requested','app_launched'])
        self.assertEqual(record['milestones'][-1]['time'],'01:24:36.281')
        for forbidden in ('SENSITIVE','SECRET','Private-Session','TOKEN','/private/'):
            self.assertNotIn(forbidden,json.dumps(result))
    def test_malformed_and_unrelated_lines_do_not_fabricate_progress(self):
        (self.staging/'Session-synthetic.log').write_text(
            'Launching app with identifier: SENSITIVE\n'
            '99:99:99.999 xcodebuild[50:60] UUID: Launching app with identifier: SENSITIVE\n'
            '01:15:52.941 other[50:60] UUID: Launching app with identifier: SENSITIVE\n')
        self.assertEqual(self.collect()['sessions'][0]['milestones'],[])
    def test_missing_staging_is_unavailable_evidence_not_success(self):
        result=self.collect() # Existing empty staging is distinct from missing.
        self.assertEqual(result['sessions'],[])
        other=self.scope/'missing'
        self.m.record_native_failure_progress(self.run,other,lambda:None)
        self.assertEqual(self.run.meta['native_failure_progress']['status'],'missing_staging')
    def test_symlinked_staging_and_session_are_never_read(self):
        for kind in ('root','leaf'):
            with self.subTest(kind=kind):
                scope=self.scope/kind;scope.mkdir()
                if kind=='root':(scope/'result.xcresult').symlink_to(self.scope/'result.xcresult',target_is_directory=True)
                else:
                    staging=scope/'result.xcresult/Staging';staging.mkdir(parents=True)
                    (staging/'Session-synthetic.log').symlink_to(self.staging/'outside')
                self.m.record_native_failure_progress(self.run,scope,lambda:None)
                self.assertEqual(self.run.meta['native_failure_progress']['status'],'unavailable')
    def test_oversized_file_is_rejected_before_open(self):
        with (self.staging/'Session-large.log').open('wb') as stream:stream.truncate(256*1024+1)
        original=self.m.os.open;files=[]
        def opened(name,*args,**kwargs):
            if str(name).startswith('Session-'):
                files.append(name);raise AssertionError('must not open')
            return original(name,*args,**kwargs)
        with mock.patch.object(self.m.os,'open',opened):
            self.assertEqual(self.collect()['status'],'unavailable')
        self.assertEqual(files,[])
    def test_entry_and_session_counts_are_bounded(self):
        for count,session in ((129,False),(5,True)):
            with self.subTest(count=count):
                scope=self.scope/str(count);staging=scope/'result.xcresult/Staging';staging.mkdir(parents=True)
                for index in range(count):(staging/(f'Session-{index}.log' if session else f'{index}.txt')).touch()
                self.m.record_native_failure_progress(self.run,scope,lambda:None)
                self.assertEqual(self.run.meta['native_failure_progress']['status'],'unavailable')
    def test_replaced_file_cannot_be_mislabeled_with_prior_identity(self):
        path=self.staging/'Session-synthetic.log';path.write_text('original')
        original=self.m.os.open
        def replaced(name,*args,**kwargs):
            if name==path.name:
                replacement=self.staging/'replacement';replacement.write_text('replacement')
                replacement.replace(path)
            return original(name,*args,**kwargs)
        with mock.patch.object(self.m.os,'open',replaced):result=self.collect()
        self.assertEqual(result['status'],'unavailable')
    def test_existing_phase_and_local_read_deadlines_do_not_replace_failure(self):
        def expired():raise TimeoutError('existing phase')
        self.assertEqual(self.collect(expired)['status'],'unavailable')
        with mock.patch.object(self.m.time,'monotonic',side_effect=[100,102]):
            self.assertEqual(self.collect()['status'],'unavailable')
    def test_replaced_directory_is_not_followed_and_all_owned_fds_close(self):
        original_open,original_close=self.m.os.open,self.m.os.close;opened=[];closed=[]
        def replacement(name,*args,**kwargs):
            if name=='Diagnostics':
                old=self.staging.with_name('old');self.staging.rename(old)
                self.staging.symlink_to(old,target_is_directory=True)
            fd=original_open(name,*args,**kwargs);opened.append(fd);return fd
        def close(fd):closed.append(fd);return original_close(fd)
        with mock.patch.object(self.m.os,'open',replacement),mock.patch.object(self.m.os,'close',close):
            self.assertEqual(self.collect()['status'],'unavailable')
        self.assertEqual(sorted(opened),sorted(closed))
    def test_milestone_and_depth_caps_remain_diagnostic_failures(self):
        path=self.staging/'Session-repeated.log'
        path.write_text('01:15:32.269 xcodebuild[50:60] Test runner session acquired connection.\n'*33)
        self.assertEqual(self.collect()['status'],'unavailable')
        path.unlink();deep=self.staging
        for index in range(13):deep=deep/str(index);deep.mkdir()
        self.assertEqual(self.collect()['status'],'unavailable')


class NativeStoreKitBindingTests(unittest.TestCase):
    def setUp(self):self.m=load('native_storekit_test',DRIVER);self.now=dt.datetime.now(dt.timezone.utc)
    def test_eight_existing_cases_share_one_unchanged_bounded_command(self):
        plan=self.m.validate_test_plan(json.loads((ROOT/'CleanSend.xctestplan').read_bytes()))
        self.assertEqual(len(plan['cases']),8);self.assertEqual(plan['maximum_case_seconds'],180);self.assertEqual(plan['outer_seconds'],300)
        args=self.m.test_arguments('A09F18F8-31EF-432D-A426-0197E73D75E8',Path('/fixture/result.xcresult'),Path('/fixture/native-unit-host.xctestrun'))
        self.assertEqual(args[:4],['xcodebuild','test-without-building','-xctestrun','/fixture/native-unit-host.xctestrun'])
        self.assertNotIn('-project',args);self.assertNotIn('-testPlan',args)
        self.assertEqual([a for a in args if a.startswith('-only-testing:')],['-only-testing:CleanSendTests/ProStoreTests'])
        self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'180')
        self.assertEqual(args[args.index('-parallel-testing-enabled')+1],'NO')
    def test_exact_identity_set_and_no_skips_required(self):
        data={'nodes':[{'nodeType':'Test Case','nodeIdentifier':name+'()','result':'Passed'} for name in sorted(self.m.CASES)]}
        self.assertEqual(self.m.accepted_cases(data),sorted(self.m.CASES))
        for replacement in ('Skipped','Failed'):
            altered=json.loads(json.dumps(data));altered['nodes'][0]['result']=replacement
            with self.assertRaises(AssertionError):self.m.accepted_cases(altered)
        data['nodes'][0]=data['nodes'][1]
        with self.assertRaises(AssertionError):self.m.accepted_cases(data)
    def test_job_time_reserves_original_native_cleanup_and_upload(self):
        accepted=self.m.admit_job(jobs(self.now,420),'123','1','a'*40,self.now,1200)
        self.assertEqual(accepted['remaining_job_seconds'],1380)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,421),'123','1','a'*40,self.now,1200)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,-1),'123','1','a'*40,self.now,1200)
    def test_dedicated_job_identity_in_four_job_run(self):
        data=jobs(self.now)
        for index,name in enumerate(('macOS core, independent export corpus, iOS build','Russian iPad privacy at system AX5','Exact packaged Release share smoke'),8):
            data['jobs'].append(dict(data['jobs'][0],id=index,name=name,status='completed'))
        data['total_count']=4
        self.assertEqual(self.m.admit_job(data,'123','1','a'*40,self.now,1200)['job_id'],7)
        # A legacy Main row, even with valid identity/time, cannot own native work.
        wrong=json.loads(json.dumps(data));wrong['jobs'][0]['name']='legacy-main'
        with self.assertRaises(AssertionError):self.m.admit_job(wrong,'123','1','a'*40,self.now,1200)
        duplicate=json.loads(json.dumps(data));duplicate['jobs'][1]['name']=duplicate['jobs'][0]['name']
        with self.assertRaises(AssertionError):self.m.admit_job(duplicate,'123','1','a'*40,self.now,1200)
        data['jobs'].append(dict(data['jobs'][1],id=12,name='unexpected fifth job'));data['total_count']=5
        with self.assertRaises(AssertionError):self.m.admit_job(data,'123','1','a'*40,self.now,1200)
    def test_dedicated_build_budget_does_not_renew_native_allowance(self):
        # The actual current139s preparation fits; a full9m build plus profile
        # cannot borrow the original30min job's180s cleanup/upload reserve.
        result=self.m.admit_job(jobs(self.now,139),'123','1','a'*40,self.now,1200)
        self.assertEqual(result['remaining_job_seconds']-result['required_remaining_seconds'],281)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,600),'123','1','a'*40,self.now,1200)
        with self.assertRaises(AssertionError):self.m.admit_job(jobs(self.now,421),'123','1','a'*40,self.now,1200)
    def test_wrong_head_attempt_runner_and_plan_fail_closed(self):
        for key,value in (('head_sha','b'*40),('run_attempt',2),('labels',['macos-14']),('labels',['macos-15-intel']),('labels',['macos-15-large'])):
            data=jobs(self.now);data['jobs'][0][key]=value
            with self.assertRaises(AssertionError):self.m.admit_job(data,'123','1','a'*40,self.now,1200)
        plan=json.loads((ROOT/'CleanSend.xctestplan').read_bytes());plan['defaultOptions']['maximumTestExecutionTimeAllowance']=240
        with self.assertRaises(AssertionError):self.m.validate_test_plan(plan)
    def test_wrong_host_rejected_before_metadata_or_scope_creation(self):
        env={'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS'}
        for architecture in ('x86_64','unknown'):
            with self.subTest(architecture=architecture),mock.patch.dict(os.environ,env),mock.patch.object(os,'uname',return_value=SimpleNamespace(machine=architecture)),mock.patch.object(self.m,'load',side_effect=AssertionError('transport must not load')):
                with self.assertRaisesRegex(AssertionError,'ARM host profile'):self.m.prepare_context(time.monotonic())

    def test_actual_context_preparation_does_one_metadata_read_and_drops_tokens(self):
        with tempfile.TemporaryDirectory(prefix='redact-payment-bind-') as temp:
            root=Path(temp).resolve();calls=[];window=load('native_window_fixture',MODULES/'window.py')
            class FakeTransport:
                def __init__(self,*_):self.report={'job_metadata':{'cleanup_confirmed':True}}
                @contextlib.contextmanager
                def command(inner,kind,limit,cap,argv,env):
                    calls.append((kind,limit,cap,argv(None)));yield io.BytesIO(json.dumps(jobs(self.now)).encode())
            transport=SimpleNamespace(Transport=FakeTransport,GH='/fixture/gh',environment=lambda *_:{})
            env={'GITHUB_ACTIONS':'true','RUNNER_OS':'macOS','GITHUB_EVENT_NAME':'pull_request','GITHUB_REPOSITORY':self.m.REPO,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','EXPECTED_HEAD_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GH_TOKEN':'fixture-secret','GITHUB_TOKEN':'other-secret'}
            with mock.patch.object(os,'uname',return_value=SimpleNamespace(machine='arm64')),mock.patch.dict(os.environ,env),mock.patch.object(self.m,'ROOT',root),mock.patch.object(self.m,'load',side_effect=lambda name:window if name=='window' else transport),mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=100*2**30)),mock.patch.object(subprocess,'Popen',side_effect=AssertionError('real process forbidden')):
                started=time.monotonic();path,context=self.m.prepare_context(started)
                self.assertNotIn('GH_TOKEN',os.environ);self.assertNotIn('GITHUB_TOKEN',os.environ)
                self.assertEqual(len(calls),1);self.assertEqual(calls[0][:3],('job_metadata',12,1024*1024))
                os.environ['NATIVE_STOREKIT_CONTEXT_SHA']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(self.m.validate_context(path,started),context)
                self.assertEqual(context['case_identities'],sorted(self.m.CASES))
                self.assertNotIn('fixture-secret',path.read_text())
                self.assertNotIn('other-secret',(path.parent/'admission.json').read_text())

    def test_actual_supervisor_timeout_keeps_child_ownership_and_cleanup_obligation(self):
        for correct_parent in (True,False):
            with self.subTest(correct_parent=correct_parent),tempfile.TemporaryDirectory(prefix='redact-payment-stop-') as temp:
                scope=Path(temp).resolve();self.m.SCOPE=scope;self.m.OWNED_ROOT=scope
                context=scope/'context.json';context.write_bytes(b'{}')
                lifecycle=load('native_cleanup_fixture',MODULES/'lifecycle.py')
                process=SimpleNamespace(pid=500,returncode=None)
                process.poll=lambda:process.returncode
                process.wait=lambda **_:process.returncode
                signals=[];child_present=[True]
                parent_env={'GH_TOKEN':'fixture-secret','GITHUB_TOKEN':'other-secret','DYLD_LIBRARY_PATH':'unexpected','SDKROOT':'unexpected'}
                if correct_parent:parent_env.update({key:'fixed-'+key for key in lifecycle.NATIVE_CONTEXT_KEYS})
                def killpg(pid,sig):
                    signals.append((pid,sig))
                    if pid==700 and sig==0 and not child_present[0]:raise ProcessLookupError()
                    if pid==700 and sig==signal.SIGKILL:child_present[0]=False
                    if pid==500 and sig==signal.SIGKILL:process.returncode=-9
                def spawn(*args,**kwargs):
                    for key in ('GH_TOKEN','GITHUB_TOKEN','DYLD_LIBRARY_PATH','SDKROOT'):
                        self.assertNotIn(key,kwargs['env'])
                    for key in lifecycle.NATIVE_CONTEXT_KEYS:
                        if correct_parent:self.assertEqual(kwargs['env'][key],parent_env[key])
                        else:self.assertNotIn(key,kwargs['env'])
                    native_env=lifecycle.child_environment(kwargs['env'])
                    for key in lifecycle.NATIVE_CONTEXT_KEYS:
                        if correct_parent:self.assertEqual(native_env[key],parent_env[key])
                        else:self.assertNotIn(key,native_env)
                    (scope/'metadata.json').write_text(json.dumps({'owner_worker_pid':500,'owned_device_name':'fixture-owned-device','commands':[{'owned_process_group':700,'args':['xcodebuild'],'owned_group_absent':False}]}))
                    return process
                aggregate=self.m.aggregate_command_groups
                with mock.patch.dict(os.environ,parent_env,clear=True),mock.patch.object(self.m,'load',return_value=lifecycle),mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(self.m.Resources,'check',side_effect=AssertionError('injected allocation floor')),mock.patch.object(self.m,'await_cleanup_ack',side_effect=subprocess.TimeoutExpired('fixture-worker',3)),mock.patch.object(subprocess,'check_output',return_value='500\n' if correct_parent else '999\n') as parent_lookup,mock.patch.object(os,'getpgid',return_value=700),mock.patch.object(os,'killpg',side_effect=killpg),mock.patch.object(lifecycle,'stop_group',side_effect=lambda proc,row:row.update(owned_group_absent=True)),mock.patch.object(self.m,'aggregate_command_groups',side_effect=lambda meta,start:aggregate(meta,start,probe=killpg)),mock.patch.object(self.m,'terminal_stdout',return_value=True):
                    self.assertEqual(self.m.supervise(context,{},time.monotonic()),1)
                receipt=json.loads((scope/'invocation-final.json').read_bytes())
                self.assertNotIn('last_resort_error',receipt)
                self.assertEqual(parent_lookup.call_args.args[0],['ps','-p','700','-o','ppid='])
                expected='signal_sent_absence_not_established' if correct_parent else 'identity_mismatch_no_signal'
                self.assertEqual(receipt['last_resort_children'],[{'pid':700,'status':expected}])
                self.assertEqual((700,signal.SIGKILL) in signals,correct_parent)
                self.assertEqual(receipt['owned_command_groups']['all_absent'],correct_parent)
                self.assertFalse(receipt['cleanup_obligation']['absence_verified'])
                self.assertTrue(receipt['cleanup_obligation']['cleanup_required'])
                self.assertEqual(receipt['status'],'failed')

class NativeStartupBudgetTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_budget_driver',DRIVER)
        self.l=self.m.load('lifecycle')
        self.clock=[183.0];self.start=100.0
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.l.OUT=Path(self.temp.name).resolve();self.l.ROOT=self.l.OUT
        self.clock_patch=mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]);self.clock_patch.start();self.addCleanup(self.clock_patch.stop)
        self.run=self.l.Run();self.run.start=self.start;self.run.persist=lambda:None
        self.phases=[]
        def check(phase):
            self.phases.append(phase)
            assert self.clock[0]<self.start+phase,'original phase deadline'
        self.resources=SimpleNamespace(check=check)
    def test_cold_readiness_retains_original376_with_full_pre_and_post_checks(self):
        self.clock[0]=116;costs=iter((1,60));checks=[];waits=[]
        def check(phase):
            checks.append(phase);self.clock[0]+=next(costs)
            self.assertLess(self.clock[0],self.start+phase)
        proc=SimpleNamespace(pid=77,returncode=None)
        def wait(timeout):waits.append(timeout);self.clock[0]+=145;proc.returncode=0
        proc.wait=wait
        with mock.patch.object(subprocess,'Popen',return_value=proc),mock.patch.object(self.l,'stop_group',side_effect=lambda p,row:row.update(owned_group_absent=True)):
            self.m.wait_ready_once(self.run,SimpleNamespace(check=check),'owned')
        self.assertEqual(checks,[376,376]);self.assertEqual(self.clock[0]-self.start,222)
        self.assertEqual(waits,[300]);self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,980)
    def test_late_native_persistence_cannot_use_stale_startup_allowance(self):
        self.run.persist=lambda:self.clock.__setitem__(0,472)
        with mock.patch.object(subprocess,'Popen') as spawn:
            with self.assertRaises(TimeoutError):self.m.wait_ready_once(self.run,self.resources,'owned')
        spawn.assert_not_called();self.assertEqual(self.run.start,100)
    def test_owned_cleanup_maxima_stay_inside_original100_reserve(self):
        self.clock[0]=self.start+980;calls=[]
        def spawn(args,**kwargs):
            proc=SimpleNamespace(pid=77+len(calls),returncode=None)
            def wait(timeout):calls.append((args[2],args[3],timeout));self.clock[0]+=timeout;proc.returncode=0
            proc.wait=wait;return proc
        with mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(self.l,'stop_group',side_effect=lambda p,row:row.update(owned_group_absent=True)):
            for name,limit,end in [('shutdown',45,1039),('delete',25,1058),('list',15,1080)]:
                self.run.end=end;self.run.command(['xcrun','simctl',name,'owned'],name+'.log',limit)
        self.assertEqual(calls,[('shutdown','owned',45),('delete','owned',25),('list','owned',15)])
        self.assertLess(self.clock[0],self.start+1080)
        self.assertEqual(self.run.start,100)

    def test_readiness_timeout_uses_actual_owned_group_stop_and_preserves_cleanup(self):
        self.clock[0]=294;present=[True];signals=[]
        proc=SimpleNamespace(pid=77,returncode=None)
        proc.poll=lambda:proc.returncode
        def wait(timeout):
            self.assertEqual(timeout,178);self.clock[0]+=timeout
            raise subprocess.TimeoutExpired('bootstatus',timeout)
        proc.wait=wait
        def killpg(pid,sig):
            self.assertEqual(pid,77);signals.append(sig)
            if not present[0]:raise ProcessLookupError()
            if sig:present[0]=False;proc.returncode=-int(sig)
        with mock.patch.object(subprocess,'Popen',return_value=proc) as spawn,mock.patch.object(os,'killpg',side_effect=killpg):
            with self.assertRaises(subprocess.TimeoutExpired):self.m.wait_ready_once(self.run,self.resources,'owned')
        self.assertEqual(spawn.call_count,1);self.assertIn(signal.SIGTERM,signals)
        self.assertEqual(proc.returncode,-15);self.assertFalse(present[0])
        record=self.run.meta['commands'][0]
        self.assertTrue(record['owned_group_absent']);self.assertEqual(record['returncode'],-15)
        self.assertEqual(self.clock[0],472);self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,980)
        self.assertEqual(self.l.CLEANUP_END,1080);self.assertEqual(self.l.TOTAL,1200)
        # Exhausted startup cannot relaunch readiness even though work remains.
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')) as late:
            with self.assertRaises(TimeoutError):self.m.wait_ready_once(self.run,self.resources,'owned')
        late.assert_not_called()

    def test_late_readiness_does_not_spawn_or_extend_an_earlier_phase(self):
        self.clock[0]=472
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')) as spawn:
            with self.assertRaises(TimeoutError):self.m.wait_ready_once(self.run,self.resources,'owned')
        spawn.assert_not_called();self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,980)
        self.run.end=150;self.clock[0]=246
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')) as spawn:
            with self.assertRaises(TimeoutError):self.m.wait_ready_once(self.run,self.resources,'owned')
        spawn.assert_not_called();self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,150)

    def test_readiness_cannot_bypass_unresolved_owned_group(self):
        self.run.meta['commands'].append({'owned_group_absent':False,'owned_process_group':99})
        with mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native forbidden')) as spawn:
            with self.assertRaisesRegex(AssertionError,'Prior owned child group unresolved'):
                self.m.wait_ready_once(self.run,self.resources,'owned')
        spawn.assert_not_called();self.assertEqual(self.run.start,100);self.assertEqual(self.run.end,980)

    def test_phase_never_extends_an_earlier_deadline_and_restores_after_failure(self):
        self.run.end=150;self.clock[0]=249
        with self.assertRaises(AssertionError):
            with self.m.work_phase(self.run,self.resources,376):
                self.assertEqual(self.run.end,150);self.clock[0]=250
        self.assertEqual(self.run.end,150);self.assertEqual(self.run.start,100)
    def test_inventory_checks_during_and_after_hashing(self):
        self.run.end=526;self.clock[0]=625
        def inventory(path,budget,check):
            check();self.clock[0]=626
            return {'hash':'unchanged'}
        with self.assertRaises(AssertionError):self.m.phase_payload_inventory(self.run,self.resources,SimpleNamespace(payload_inventory=inventory),None,'/fixture/app')
        self.assertEqual(self.phases,[526,526,526])
    def test_actual_resource_scan_respects_phase_after_each_stat(self):
        self.clock[0]=625;self.m.SCOPE=Path('/fixture');self.m.OWNED_ROOT=self.m.SCOPE
        resources=self.m.Resources(self.start)
        def late_stat(path):
            self.clock[0]=626
            return SimpleNamespace(st_blocks=0,st_mode=0o040700)
        with mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=32*2**30)),mock.patch.object(os,'walk',return_value=[('/fixture',[],[])]),mock.patch.object(os,'lstat',side_effect=late_stat):
            with self.assertRaisesRegex(AssertionError,'owned stat deadline'):resources.check(526)
    def test_test_budget_retains300_body4_stop150_final_and_rejects_late_admission(self):
        self.clock[0]=626
        self.assertEqual(self.m.native_test_end(self.run,self.clock[0]),926)
        self.assertEqual(self.m.TEST_STOP_END-self.m.TEST_BODY_END,4)
        self.assertEqual(self.m.FINAL_VERIFY_END-self.m.TEST_STOP_END,150)
        self.clock[0]=626.001
        with self.assertRaises(AssertionError):self.m.native_test_end(self.run,self.clock[0])
        self.assertEqual(self.run.start,100)
    def test_final_inventory_has_original980_deadline(self):
        self.run.end=980;self.clock[0]=1079
        def inventory(path,budget,check):check();self.clock[0]=1080;return {}
        with self.assertRaises(AssertionError):self.m.phase_payload_inventory(self.run,self.resources,SimpleNamespace(payload_inventory=inventory),None,'/fixture/app')
        self.assertEqual(self.phases,[980,980,980])

class NativePolicyWindowTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_policy_window',DRIVER)
    def test_native_module_instance_policy_does_not_change_package_defaults(self):
        native=self.m.load('lifecycle');package=load('package_default_lifecycle',MODULES/'lifecycle.py')
        fields=('TOTAL','WORK_END','RECOVERY_END','SHUTDOWN_END','DELETE_END','CLEANUP_END')
        self.assertEqual(tuple(getattr(native,k) for k in fields),(1200,980,1002,1039,1058,1080))
        self.assertEqual(tuple(getattr(package,k) for k in fields),(900,680,702,739,758,780))
        run=native.Run()
        self.assertEqual(run.end,980);self.assertEqual(run.meta['total_seconds'],1200)
        self.assertEqual(run.meta['phase_deadlines_seconds'],{'work':980,'recovery':1002,'shutdown':1039,'delete':1058,'absence':1080,'evidence':1192})
        self.assertEqual(self.m.NATIVE_PHASES,{'startup':376,'test_latest_start':526,'test_body':826,'test_stop':830,'final_verification':980,'work':980,'recovery':1002,'shutdown':1039,'delete':1058,'absence':1080,'evidence':1192,'whole':1200})
    def test_cleanup_ack_uses1080_and_rejects_old660_identity(self):
        for correct in (True,False):
            with self.subTest(correct=correct):
                clock=[1000.0];intent={};proc=SimpleNamespace(poll=lambda:None)
                def read():return {'cleanup_phase':{'entered_monotonic':999,'absolute_deadline':1080 if correct else 660},'device_removed':True}
                self.m.await_cleanup_ack(proc,0,intent,clock=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n),read=read)
                self.assertEqual(bool(intent.get('cleanup_acknowledged')),correct)
                self.assertEqual(bool(intent.get('device_absence_observed')),correct)
                self.assertLessEqual(clock[0],1005)
    def test_terminal_io_uses_original1200_without_renewal(self):
        with tempfile.TemporaryDirectory() as temp:
            self.m.SCOPE=Path(temp);record={'status':'fixture'}
            self.m.final_write(record,0,clock=lambda:1000)
            self.assertEqual(json.loads((self.m.SCOPE/'invocation-final.json').read_bytes()),record)
            with mock.patch.object(os,'open') as opened:
                with self.assertRaises(AssertionError):self.m.final_write(record,0,clock=lambda:1200)
            opened.assert_not_called()
        write=mock.Mock()
        self.assertFalse(self.m.terminal_stdout(record,0,clock=lambda:1200,write=write));write.assert_not_called()

class InstalledInventoryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_inventory_receipt',DRIVER)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name).resolve()/'installed-during.json'
        self.clock=[100.0];self.run=SimpleNamespace(start=100.0,end=526)
        self.patch=mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]);self.patch.start();self.addCleanup(self.patch.stop)
        self.resources=SimpleNamespace(check=lambda phase:self.assertLess(self.clock[0],self.run.start+phase))
    def test_mismatch_is_persisted_then_rejected_with_sorted_exact_changes(self):
        expected={'.':{'directory':True,'mode':'0755'},'remove':{'mode':'0644','sha256':'a'},'mode':{'mode':'0644','sha256':'b'},'hash':{'mode':'0644','sha256':'c'},'type':{'directory':True,'mode':'0755'}}
        actual={'.':expected['.'],'add':{'mode':'0644','sha256':'d'},'mode':{'mode':'0600','sha256':'b'},'hash':{'mode':'0644','sha256':'changed'},'type':{'mode':'0755','sha256':'e'}}
        with self.assertRaisesRegex(AssertionError,'inventory saved'):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',actual,expected,self.path)
        saved=json.loads(self.path.read_bytes());self.assertFalse(saved['exact_payload']);self.assertEqual(saved['files'],actual)
        self.assertEqual([r['path'] for r in saved['differences']],['add','hash','mode','remove','type'])
        rows={r['path']:r for r in saved['differences']}
        self.assertEqual(rows['add']['change'],'added');self.assertEqual(rows['remove']['change'],'missing')
        self.assertEqual(rows['mode']['fields'],['mode']);self.assertEqual(rows['hash']['fields'],['sha256']);self.assertIn('type',rows['type']['fields'])
        for name,row in rows.items():self.assertEqual(row['actual'],actual.get(name));self.assertEqual(row['expected'],expected.get(name))
    def test_exact_payload_still_saves_truthful_success(self):
        files={'.':{'directory':True,'mode':'0755'},'main':{'mode':'0755','sha256':'abc'}}
        saved=self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',files,files,self.path)
        self.assertTrue(saved['exact_payload']);self.assertEqual(saved['differences'],[]);self.assertEqual(json.loads(self.path.read_bytes()),saved)
    def test_expired_phase_and_oversize_receipt_fail_before_write(self):
        self.clock[0]=626
        with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        self.assertFalse(self.path.exists());self.clock[0]=100
        actual={'large':{'mode':'0644','sha256':'x'*(1024*1024)}}
        with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',actual,{},self.path)
        self.assertFalse(self.path.exists())
    def test_phase_expiring_during_serialization_never_opens_output(self):
        original=self.m.json.dumps
        def encode_then_expire(*args,**kwargs):
            raw=original(*args,**kwargs);self.clock[0]=self.run.start+self.run.end;return raw
        with mock.patch.object(self.m.json,'dumps',side_effect=encode_then_expire),mock.patch.object(Path,'open') as opened:
            with self.assertRaises(AssertionError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        opened.assert_not_called();self.assertFalse(self.path.exists())
    def test_existing_receipt_is_not_overwritten(self):
        self.path.write_bytes(b'original')
        with self.assertRaises(FileExistsError):self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',{}, {},self.path)
        self.assertEqual(self.path.read_bytes(),b'original')

class InitialInstallModeTests(unittest.TestCase):
    # Retained iOS18.5 installed-host observation, with synthetic file contents/hashes.
    observed_paths=(
        'CleanSend.debug.dylib','Frameworks/Testing.framework/Testing',
        'Frameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
        'Frameworks/XCTest.framework/XCTest','Frameworks/XCTestCore.framework/XCTestCore',
        'Frameworks/XCTestSupport.framework/XCTestSupport','Frameworks/XCUIAutomation.framework/XCUIAutomation',
        'Frameworks/XCUnit.framework/XCUnit','Frameworks/libXCTestBundleInject.dylib',
        'Frameworks/libXCTestSwiftSupport.dylib','PlugIns/CleanSendShare.appex/CleanSendShare.debug.dylib',
        'PlugIns/CleanSendShare.appex/__preview.dylib','PlugIns/CleanSendTests.xctest/CleanSendTests','__preview.dylib')
    def setUp(self):
        self.m=load('initial_install_modes',DRIVER)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.run=SimpleNamespace(start=time.monotonic(),end=526);self.resources=SimpleNamespace(check=lambda _:None)
        self.expected={name:{'mode':'0755','sha256':hashlib.sha256(name.encode()).hexdigest()} for name in self.observed_paths+('CleanSend','PlugIns/CleanSendShare.appex/CleanSendShare')}
        self.expected['.']={'mode':'0755','directory':True}
        self.expected['Frameworks']={'mode':'0755','directory':True}
        self.actual=json.loads(json.dumps(self.expected))
        for name in self.observed_paths:self.actual[name]['mode']='0644'
    def save(self,name,files,expected,*,initial=False):
        return self.m.persist_installed_payload(self.run,self.resources,'/fixture/app',files,expected,self.root/name,initial_install=initial)
    def test_complete_observed_transition_keeps_raw_result_and_exact_later_baseline(self):
        before=self.save('before.json',self.actual,self.expected,initial=True)
        self.assertFalse(before['exact_payload']);self.assertTrue(before['accepted_payload'])
        self.assertEqual(len(before['accepted_install_transitions']),14)
        self.assertEqual({row['path'] for row in before['accepted_install_transitions']},set(self.observed_paths))
        self.assertEqual(before['files'],self.actual)
        for name in ('during.json','after.json'):
            result=self.save(name,self.actual,before['files'])
            self.assertTrue(result['exact_payload']);self.assertEqual(result['accepted_install_transitions'],[])
        self.assertTrue(all(self.expected[name]['mode']=='0755' for name in self.observed_paths))
    def test_unknown_content_type_path_or_mode_remains_fatal_and_is_recorded(self):
        first=self.observed_paths[0]
        variants={
            'changed-hash':lambda data:data[first].update(sha256='0'*64),
            'wrong-mode':lambda data:data[first].update(mode='0600'),
            'directory':lambda data:data[first].update(directory=True),
            'unknown-field':lambda data:data[first].update(extra=True),
            'added':lambda data:data.update(extra={'mode':'0644','sha256':'0'*64}),
            'missing':lambda data:data.pop(first),
            'main-executable':lambda data:data['CleanSend'].update(mode='0644'),
            'extension-executable':lambda data:data['PlugIns/CleanSendShare.appex/CleanSendShare'].update(mode='0644'),
            'directory-mode':lambda data:data['Frameworks'].update(mode='0700'),
        }
        for name,mutate in variants.items():
            with self.subTest(name=name):
                data=json.loads(json.dumps(self.actual));mutate(data)
                with self.assertRaisesRegex(AssertionError,'bounded inventory saved'):
                    self.save(name+'.json',data,self.expected,initial=True)
                saved=json.loads((self.root/(name+'.json')).read_bytes())
                self.assertFalse(saved['accepted_payload']);self.assertEqual(saved['accepted_install_transitions'],[])
                self.assertEqual(saved['files'],data)
    def test_partial_transition_is_not_general_mode_normalization(self):
        partial=json.loads(json.dumps(self.actual));partial[self.observed_paths[0]]['mode']='0755'
        with self.assertRaises(AssertionError):self.save('partial.json',partial,self.expected,initial=True)
        exact=self.save('unchanged.json',self.expected,self.expected,initial=True)
        self.assertTrue(exact['exact_payload']);self.assertEqual(exact['accepted_install_transitions'],[])
    def test_later_mode_or_hash_change_cannot_reuse_install_exception(self):
        for index,change in enumerate(({'mode':'0755'},{'sha256':'0'*64})):
            data=json.loads(json.dumps(self.actual));data[self.observed_paths[0]].update(change)
            with self.assertRaises(AssertionError):self.save(str(index)+'.json',data,self.actual)
        with self.assertRaises(AssertionError):self.save('not-initial.json',self.actual,self.expected)

class NativeResourceScanTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_resource_scan',DRIVER);self.clock=[101.0]
        self.m.SCOPE=self.m.OWNED_ROOT=Path('/fixture/private-owned-root')
        patches=(mock.patch.object(time,'monotonic',new=lambda:self.clock[0]),
                 mock.patch.object(self.m.shutil,'disk_usage',return_value=SimpleNamespace(free=32*2**30)),
                 mock.patch.object(subprocess,'Popen',side_effect=AssertionError('native/network forbidden')),
                 mock.patch.object(os,'killpg',side_effect=AssertionError('signals forbidden')))
        for patch in patches:patch.start();self.addCleanup(patch.stop)
    @staticmethod
    def info(blocks,mode=0o100600):return SimpleNamespace(st_blocks=blocks,st_mode=mode)
    def test_complete_two_root_scan_keeps_both_directory_stats_and_all_allocations(self):
        owned=str(self.m.OWNED_ROOT);device='/fixture/device';device_dirs=['data','link']
        rows={owned:[(owned,['Products'],['receipt.json']),(owned+'/Products',[],['app'])],
              device:[(device,device_dirs,[]),(device+'/data',[],['state'])]}
        values={owned:self.info(4,0o040700),owned+'/Products':self.info(2,0o040700),
                owned+'/receipt.json':self.info(1),owned+'/Products/app':self.info(5),
                device:self.info(3,0o040700),device+'/data':self.info(4,0o040700),
                device+'/link':self.info(1,0o120777),device+'/data/state':self.info(7)}
        resources=self.m.Resources(100);resources.device=Path(device)
        with mock.patch.object(Path,'exists',return_value=True),mock.patch.object(os,'walk',side_effect=lambda root,**kw:rows[str(root)]) as walk,mock.patch.object(os,'lstat',side_effect=lambda path:values[path]) as stat_call:
            resources.check(196)
        self.assertEqual(resources.maximum,33*512)
        names=[call.args[0] for call in stat_call.call_args_list]
        self.assertEqual(len(names),10)  # R + 2D + F = 2 + 4 + 4; no stats omitted.
        self.assertEqual(names.count(owned+'/Products'),2);self.assertEqual(names.count(device+'/data'),2)
        self.assertEqual(names.count(device+'/link'),1);self.assertNotIn('link',device_dirs)
        self.assertEqual([call.kwargs for call in walk.call_args_list],[{'followlinks':False}]*2)
        self.assertIsNone(resources.first_failure)
    def test_successful_scan_counters_measure_existing_work_without_extra_walks(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        def observe(path):self.clock[0]+=.1;return self.info(1,0o040700)
        with mock.patch.object(os,'walk',return_value=[(root,[],[])]) as walk,mock.patch.object(os,'lstat',side_effect=observe):
            resources.check(196);resources.check(196)
            self.assertEqual(walk.call_count,1)
            self.clock[0]+=2;resources.check(196);self.assertEqual(walk.call_count,2)
        self.assertEqual(resources.scan_totals['count'],2)
        self.assertEqual(resources.scan_totals['total_lstat_calls'],2)
        self.assertEqual(resources.scan_totals['max_lstat_calls'],1)
        self.assertEqual(resources.scan_totals['max_directory_visits'],1)
        self.assertAlmostEqual(resources.scan_totals['total_seconds'],.2)
        self.assertAlmostEqual(resources.scan_totals['max_seconds'],.1)
    def test_changed_or_replaced_directory_is_reobserved_at_traversal(self):
        root=str(self.m.OWNED_ROOT);seen=[]
        def observe(path):
            seen.append(path)
            if path==root:return self.info(1,0o040700)
            if path==root+'/child':return self.info(2 if seen.count(path)==1 else 20,0o040700)
            return self.info(3)
        resources=self.m.Resources(100)
        with mock.patch.object(os,'walk',return_value=[(root,['child'],[]),(root+'/child',[],['file'])]),mock.patch.object(os,'lstat',side_effect=observe):resources.check(196)
        self.assertEqual(resources.maximum,(1+2+20+3)*512)
        self.assertEqual(seen.count(root+'/child'),2)
    def test_real_walk_does_not_follow_directory_replaced_by_symlink(self):
        with tempfile.TemporaryDirectory(prefix='native-scan-links-') as temporary:
            root=Path(temporary)/'owned';outside=Path(temporary)/'outside'
            root.mkdir();outside.mkdir();child=root/'child';child.mkdir()
            (child/'old').write_bytes(b'old');(outside/'never-read').write_bytes(b'outside')
            self.m.OWNED_ROOT=root;resources=self.m.Resources(100)
            original_walk=os.walk;original_stat=os.lstat;visited=[];stats=[]
            def changing_walk(*args,**kwargs):
                self.assertFalse(kwargs['followlinks'])
                for row in original_walk(*args,**kwargs):
                    visited.append(row[0]);yield row
                    if row[0]==str(root):
                        child.rename(outside/'previous');child.symlink_to(outside,target_is_directory=True)
            def observe(path,*args,**kwargs):stats.append(os.fspath(path));return original_stat(path,*args,**kwargs)
            with mock.patch.object(os,'walk',side_effect=changing_walk),mock.patch.object(os,'lstat',side_effect=observe):resources.check(196)
            self.assertEqual(visited,[str(root)])
            self.assertFalse(any(name.startswith(str(outside)) for name in stats))
            self.assertIsNone(resources.first_failure)
    def test_each_worker_and_supervisor_sample_is_fresh_and_independent(self):
        root=str(self.m.OWNED_ROOT);blocks=[1];worker=self.m.Resources(100);supervisor=self.m.Resources(100)
        with mock.patch.object(os,'walk',side_effect=lambda *a,**k:iter([(root,[],[])])),mock.patch.object(os,'lstat',side_effect=lambda path:self.info(blocks[0],0o040700)) as observed:
            worker.check(196);supervisor.check(772)
            self.assertEqual(observed.call_count,2)
            blocks[0]=7;self.clock[0]+=2;worker.check(196)
            self.assertEqual(worker.maximum,7*512);self.assertEqual(supervisor.maximum,512)
            supervisor.check(772);self.assertEqual(observed.call_count,4);self.assertEqual(supervisor.maximum,7*512)
    def test_first_deadline_failure_has_bounded_counters_and_is_not_overwritten(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        def observe(path):
            if path!=root:self.clock[0]=296
            return self.info(1)
        with mock.patch.object(os,'walk',return_value=[(root,[],['secret-token'])]),mock.patch.object(os,'lstat',side_effect=observe),mock.patch.object(Path,'open',side_effect=AssertionError('failure I/O forbidden')):
            with self.assertRaisesRegex(AssertionError,'owned stat deadline'):resources.check(196)
        failure=dict(resources.first_failure)
        self.assertEqual(failure['operation'],'stat_deadline');self.assertEqual(failure['root'],'owned')
        self.assertEqual(failure['successful_lstat_count'],2);self.assertEqual(failure['lstat_calls'],2)
        self.assertEqual(failure['charged_allocated_bytes'],512);self.assertFalse(failure['complete_scan'])
        self.assertEqual(failure['deadline_monotonic'],296);self.assertEqual(failure['elapsed_seconds'],196)
        self.assertEqual(failure['roots']['owned']['lstat_calls'],2);self.assertFalse(failure['roots']['owned']['complete'])
        self.assertLess(len(json.dumps(failure)),2048);self.assertNotIn('secret',json.dumps(failure));self.assertNotIn('/fixture',json.dumps(failure))
        self.clock[0]=101
        with mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',side_effect=PermissionError('credential must not enter evidence')):
            with self.assertRaises(PermissionError):resources.check(772)
        self.assertEqual(resources.first_failure,failure)
    def test_complete_scan_over_cap_remains_fatal(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        with mock.patch.object(self.m,'CAP',512),mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',return_value=self.info(2)):
            with self.assertRaisesRegex(AssertionError,'owned allocation cap'):resources.check(196)
        failure=resources.first_failure
        self.assertTrue(failure['complete_scan']);self.assertEqual(failure['charged_allocated_bytes'],1024)
        self.assertEqual(failure['operation'],'allocation_cap')
    def test_original100000_entry_ceiling_stops_the_complete_scan(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100)
        with mock.patch.object(os,'walk',return_value=[(root,[],['file']*100000)]),mock.patch.object(os,'lstat',new=lambda path:self.info(1)):
            with self.assertRaisesRegex(AssertionError,'owned inventory entry cap'):resources.check(196)
        failure=resources.first_failure
        self.assertEqual(failure['successful_lstat_count'],100001);self.assertEqual(failure['lstat_calls'],100001)
        self.assertEqual(failure['charged_allocated_bytes'],100000*512);self.assertEqual(failure['operation'],'entry_cap')
    def test_diagnostic_failure_does_not_mask_primary_exception(self):
        root=str(self.m.OWNED_ROOT);resources=self.m.Resources(100);primary=PermissionError('private text')
        def fail(path):
            self.clock[0]=None
            raise primary
        def clock():
            if self.clock[0] is None:raise RuntimeError('diagnostic clock failure')
            return self.clock[0]
        with mock.patch.object(time,'monotonic',side_effect=clock),mock.patch.object(os,'walk',return_value=[(root,[],[])]),mock.patch.object(os,'lstat',side_effect=fail):
            with self.assertRaises(PermissionError) as caught:resources.check(196)
        self.assertIs(caught.exception,primary);self.assertIsNone(resources.first_failure)


class ExplicitUnitHostBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.products=self.root/'Products';self.products.mkdir()
        self.host=self.products/'Debug-iphonesimulator/CleanSend.app';self.host.mkdir(parents=True)
        self.unit=self.host/'PlugIns/CleanSendTests.xctest';self.unit.mkdir(parents=True)
        self.output=self.root/'selected.xctestrun';self.original=self.products/'CleanSend.xctestrun'
        self.m=load('native_explicit_host',DRIVER)
        self.target={'BlueprintName':'CleanSendTests','IsAppHostedTestBundle':True,
            'TestHostPath':'__TESTROOT__/Debug-iphonesimulator/CleanSend.app',
            'TestBundlePath':'__TESTHOST__/PlugIns/CleanSendTests.xctest','TestHostBundleIdentifier':self.m.APP_ID,
            'EnvironmentVariables':{'APP_DISTRIBUTOR_ID_OVERRIDE':'com.apple.AppStore','OS_ACTIVITY_DT_MODE':'YES','SQLITE_ENABLE_THREAD_ASSERTIONS':'1','TERM':'dumb'},
            'TestingEnvironmentVariables':{'DYLD_FRAMEWORK_PATH':'__TESTROOT__/Debug-iphonesimulator','DYLD_INSERT_LIBRARIES':'__TESTHOST__/Frameworks/libXCTestBundleInject.dylib'},
            'CommandLineArguments':[],'DefaultTestExecutionTimeAllowance':120,'MaximumTestExecutionTimeAllowance':180,
            'ProductModuleName':'CleanSendTests','InProcessParallelizationEnabled':False,
            'ClangProfileDataDirectoryPath':'__DERIVEDDATA__/Build/ProfileData',
            'DependentProductPaths':['__TESTROOT__/Debug-iphonesimulator/CleanSend.app',
                '__TESTROOT__/Debug-iphonesimulator/CleanSend.app/PlugIns/CleanSendTests.xctest']}
        self.ui={'BlueprintName':'CleanSendUITests','IsUITestBundle':True,'UITargetAppEnvironmentVariables':{},'EnvironmentVariables':{}}
        self.data={'__xctestrun_metadata__':{'FormatVersion':2},'ContainerInfo':{'ContainerName':'CleanSend','SchemeName':'CleanSend'},
            'TestPlan':{'IsDefault':True,'Name':'CleanSend'},'TestConfigurations':[{'Name':'Local Testing','TestTargets':[self.target,self.ui]}]}
    def bind(self,check=lambda:None):
        self.original.write_bytes(plistlib.dumps(self.data));return self.m.bind_unit_test_host(self.products,self.host,self.unit,self.output,check)
    def test_actual_generated_shape_bound_only_to_host_with_all_eight_cases(self):
        before=copy.deepcopy(self.data);receipt=self.bind();bound=plistlib.loads(self.output.read_bytes())
        self.assertEqual(plistlib.loads(self.original.read_bytes()),before)
        targets=bound['TestConfigurations'][0]['TestTargets'];self.assertEqual(len(targets),1);selected=targets[0]
        expected=copy.deepcopy(self.target);expected['TestHostPath']=str(self.host)
        expected['DependentProductPaths']=[value.replace('__TESTROOT__',str(self.products)) for value in expected['DependentProductPaths']]
        expected['TestingEnvironmentVariables']['DYLD_FRAMEWORK_PATH']=str(self.products/'Debug-iphonesimulator')
        expected['EnvironmentVariables'][self.m.NATIVE_HOST_MARKER]='1'
        expected.update(OnlyTestIdentifiers=sorted(self.m.CASES),SkipTestIdentifiers=[],TestTimeoutsEnabled=True)
        self.assertEqual(selected,expected);self.assertEqual(receipt['original_sha256'],hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual(receipt['bound_sha256'],hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotIn(self.m.NATIVE_HOST_MARKER,self.ui['EnvironmentVariables']);self.assertNotIn('UITargetAppEnvironmentVariables',selected)
        self.assertEqual(bound['ContainerInfo'],before['ContainerInfo']);self.assertEqual(bound['TestPlan'],before['TestPlan'])
        self.assertEqual(bound['TestConfigurations'][0]['Name'],'Local Testing')
        # Actual Xcode16.4 rc70 establishes destination-artifact mode is device-only.
        self.assertFalse(selected.get('UseDestinationArtifacts',False))
        self.assertNotIn('TestBundleDestinationRelativePath',selected)
        self.assertEqual(selected['TestHostPath'],str(self.host))
        self.assertEqual(selected['TestBundlePath'],'__TESTHOST__/PlugIns/CleanSendTests.xctest')
    def test_wrong_host_target_ui_and_preexisting_ui_marker_are_rejected(self):
        for mutate in (lambda:setitem(self.target,'TestHostPath','__TESTROOT__/Release-iphonesimulator/CleanSend.app'),
                       lambda:setitem(self.target,'BlueprintName','OtherTests'),
                       lambda:setitem(self.target,'TestHostBundleIdentifier','io.example.wrong-host'),
                       lambda:setitem(self.target,'TestBundlePath','__TESTHOST__/PlugIns/OtherTests.xctest'),
                       lambda:setitem(self.target,'UseDestinationArtifacts',True),
                       lambda:setitem(self.target,'TestBundleDestinationRelativePath','__TESTHOST__/PlugIns/Unexpected.xctest'),
                       lambda:setitem(self.target,'UITargetAppPath','__TESTROOT__/UI.app'),
                       lambda:setitem(self.target,'IsUITestBundle',True),
                       lambda:self.ui['EnvironmentVariables'].update({self.m.NATIVE_HOST_MARKER:'1'}),
                       lambda:setitem(self.target,'StoreKitConfigurationFilePath','unexpected.storekit'),
                       lambda:setitem(self.target,'MaximumTestExecutionTimeAllowance',240)):
            saved=copy.deepcopy(self.data);mutate()
            with self.assertRaises(AssertionError):self.bind()
            self.assertFalse(self.output.exists());self.data=saved;self.target,self.ui=self.data['TestConfigurations'][0]['TestTargets']
    def test_duplicate_config_and_expired_serialization_cannot_open_output(self):
        self.original.write_bytes(plistlib.dumps(self.data));(self.products/'duplicate.xctestrun').write_bytes(self.original.read_bytes())
        with self.assertRaisesRegex(AssertionError,'ambiguous'):self.m.bind_unit_test_host(self.products,self.host,self.unit,self.output,lambda:None)
        (self.products/'duplicate.xctestrun').unlink();expired=[False];original=plistlib.dumps
        def encode(value):result=original(value);expired[0]=True;return result
        def check():
            if expired[0]:raise TimeoutError('original phase')
        with mock.patch.object(plistlib,'dumps',side_effect=encode),mock.patch.object(Path,'open') as opened:
            with self.assertRaises(TimeoutError):self.m.bind_unit_test_host(self.products,self.host,self.unit,self.output,check)
        opened.assert_not_called();self.assertFalse(self.output.exists())
    def test_symlink_original_and_replaced_configuration_are_rejected(self):
        outside=self.root/'outside';outside.write_bytes(plistlib.dumps(self.data));self.original.symlink_to(outside)
        with self.assertRaises(OSError):self.m.bind_unit_test_host(self.products,self.host,self.unit,self.output,lambda:None)
        self.assertFalse(self.output.exists())
    def test_short_configuration_write_is_fatal_and_closes_output(self):
        self.original.write_bytes(plistlib.dumps(self.data))
        stream=mock.MagicMock();stream.__enter__.return_value=stream
        stream.write.side_effect=lambda raw:len(raw)-1
        with mock.patch.object(Path,'open',return_value=stream) as opened:
            with self.assertRaisesRegex(OSError,'short configuration write'):
                self.m.bind_unit_test_host(self.products,self.host,self.unit,self.output,lambda:None)
        opened.assert_called_once_with('xb');self.assertEqual(stream.write.call_count,1)
        stream.flush.assert_not_called();stream.__exit__.assert_called_once()

    def test_only_actual_fixed_inert_host_event_is_accepted(self):
        event={'event':'first.session','explicitUnitHost':True,'firstSessionInert':True,'xctestLoaded':True,'rootConstructions':0,'storeConstructions':0}
        line=lambda row:b'NATIVE_STOREKIT_HOST '+json.dumps(row).encode()+b'\n'
        self.assertTrue(self.m.observed_inert_unit_host(line(event)))
        for key,value in [('event','host.classification'),('explicitUnitHost',False),('firstSessionInert',False),('xctestLoaded',False),('rootConstructions',1),('storeConstructions',1),('rootConstructions',False)]:
            row=dict(event);row[key]=value;self.assertFalse(self.m.observed_inert_unit_host(line(row)))
        self.assertFalse(self.m.observed_inert_unit_host(b'NATIVE_STOREKIT_HOST {partial'))

class SingleInstallerWorkerTests(unittest.TestCase):
    """Run the actual worker with inert command/process and tiny filesystem fixtures."""
    def setUp(self):
        self.m=load('native_single_installer_worker',DRIVER)
        self.temp=tempfile.TemporaryDirectory(prefix='native-single-installer-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.scope=self.root/'evidence';self.scope.mkdir()
        self.m.ROOT=self.root;self.m.SCOPE=self.scope;self.m.OWNED_ROOT=self.scope
        self.uid='A09F18F8-31EF-432D-A426-0197E73D75E8'
        self.device=self.root/'home/Library/Developer/CoreSimulator/Devices'/self.uid
        self.host=self.root/'.derivedData/Build/Products/Debug-iphonesimulator/CleanSend.app'
        self.unit=self.host/'PlugIns/CleanSendTests.xctest';self.unit.mkdir(parents=True)
        (self.host/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':self.m.APP_ID,'DTXcodeBuild':'17C529','MinimumOSVersion':'17.0'}))
        (self.unit/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'io.github.4alvit.cleansend.tests'}))
        self.names=('App/CleanSend.storekit','CleanSend.xctestplan','Tests/EntitlementTests/ProStoreTests.swift')
        for name,raw in zip(self.names,(b'fixed configuration',(ROOT/'CleanSend.xctestplan').read_bytes(),b'unchanged real cases fixture')):
            file=self.root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
        (self.unit/'CleanSend.storekit').write_bytes((self.root/self.names[0]).read_bytes())
        self.scheme=self.root/'CleanSend.xcodeproj/xcshareddata/xcschemes/CleanSend.xcscheme';self.scheme.parent.mkdir(parents=True);self.scheme.write_bytes(b'fixed scheme')
        (self.scope/'context.json').write_bytes(b'{}')
        self.expected={'.':{'directory':True,'mode':'0755'},'CleanSend':{'mode':'0755','sha256':'a'*64},'PlugIns/CleanSendTests.xctest/CleanSendTests':{'mode':'0755','sha256':'b'*64}}
        self.commands=[];self.inventories=[];self.lookup_count=0;self.lifecycle=self.m.load('lifecycle')
        self.toolchain='Xcode 26.3\nBuild version 17C529';self.runtime_version='26.2';self.runtime_identifier=self.m.RUNTIME
    def exercise(self,*,start_case=True,changed_container=False,changed_bytes=False,profile_rejected=False,start_case_after=0,case_during_observation=False):
        m=self.m;clock=[100.0];phase_checks=[];sample_state={};self.sample_calls=0
        def check(phase):
            phase_checks.append(phase);assert clock[0]<90+phase
        resource=SimpleNamespace(device=None,maximum=0,first_failure=None,scan_totals={},check=check)
        def payload(path,budget,guard):
            guard();self.inventories.append(str(path));result=copy.deepcopy(self.expected)
            if changed_bytes and path!=self.host and self.lookup_count==2:result['CleanSend']['sha256']='c'*64
            guard();return result
        evidence=SimpleNamespace(payload_inventory=payload)
        budget=SimpleNamespace(safe=lambda name:None)
        def bind(products,host,unit,output,guard):
            guard();original=products/'generated.xctestrun';original.write_bytes(b'generated same-host config');output.write_bytes(b'ordinary simulator config')
            return {'original_path':str(original),'original_sha256':m.sha(original),'bound_path':str(output),'bound_sha256':m.sha(output)}
        def command(run,args,name,limit=15,required=True):
            self.commands.append([str(value) for value in args]);value=''
            if args[:2]==['git','ls-files']:value='\n'.join(self.names)
            elif args[:2]==['git','rev-parse']:value='b'*40 if str(args[2]).endswith('^{tree}') else 'a'*40
            elif args==['xcodebuild','-version']:value=self.toolchain
            elif args[:4]==['xcrun','simctl','list','runtimes']:
                value=json.dumps({'runtimes':[{'identifier':self.runtime_identifier,'isAvailable':True,'version':self.runtime_version,'supportedArchitectures':['arm64'],'supportedDeviceTypes':[{'identifier':m.DEVICE}]}]})
            elif args[:4]==['xcrun','simctl','list','devicetypes']:
                value=json.dumps({'devicetypes':[{'identifier':m.DEVICE,'minRuntimeVersionString':'17.0','maxRuntimeVersionString':'99.0'}]})
            elif args[:3]==['xcrun','simctl','create']:value=self.uid
            elif args[:3]==['xcrun','simctl','get_app_container']:
                self.lookup_count+=1
                slot='second' if changed_container and self.lookup_count==2 else 'first'
                value=str(self.device/'data/Containers/Bundle/Application'/slot/'CleanSend.app')
            elif args[:4]==['xcrun','simctl','list','devices']:value=json.dumps({'devices':{m.RUNTIME:[]}})
            elif args[:4]==['xcrun','xcresulttool','get','test-results']:
                value=json.dumps({'passedTests':8,'failedTests':0,'skippedTests':0,'totalTestCount':8} if args[4]=='summary' else {'nodes':[{'nodeType':'Test Case','nodeIdentifier':name+'()','result':'Passed'} for name in sorted(m.CASES)]})
            (self.scope/name).write_text(value)
            run.meta['commands'].append({'args':[str(v) for v in args],'returncode':0,'owned_group_absent':True})
            return 0
        def spawn(args,**kwargs):
            self.commands.append(list(args));self.assertEqual(args[:2],['xcodebuild','test-without-building'])
            self.assertEqual(kwargs['start_new_session'],True)
            (self.scope/'result.xcresult').mkdir()
            marker={'event':'first.session','explicitUnitHost':True,'firstSessionInert':True,'xctestLoaded':True,'rootConstructions':0,'storeConstructions':0}
            text=b'NATIVE_STOREKIT_HOST '+json.dumps(marker).encode()+b'\n'
            if start_case:text+=("Test Case '-[CleanSendTests.ProStoreTests "+m.CASE_NAMES[0]+"]' started.\n").encode()
            else:text+=b"Test Suite 'ProStoreTests' started.\n"
            process=SimpleNamespace(pid=99,returncode=None);command_start=clock[0];written=[False]
            def poll():
                elapsed=clock[0]-command_start
                if elapsed>=start_case_after and not written[0]:
                    kwargs['stdout'].write(text);kwargs['stdout'].flush();written[0]=True
                if elapsed>=start_case_after+1:process.returncode=0
                return process.returncode
            process.poll=poll
            def emit_during_sample():
                kwargs['stdout'].write(text);kwargs['stdout'].flush();written[0]=True;process.returncode=0
            sample_state['emit']=emit_during_sample
            return process
        def close(process,row):process.returncode=0;row['owned_group_absent']=True
        def sample_command(args,name,deadline,out,env,cwd,rows,*,run):
            self.sample_calls+=1;sample_state['emit']()
            rows.append({'kind':'diagnostic','status':'RETURNED','returncode':0,'owned_group_absent':True})
            run.meta['commands'].append(rows[-1])
        sampling=SimpleNamespace(supported=lambda:case_during_observation,CLEANUP_RESERVE=2,observe_owned=lambda proc:False,command=sample_command,OwnershipLost=RuntimeError)
        context={'head':'a'*40,'checkout':'a'*40,'run':'123','attempt':'1','job_admission':{'fixture':True}}
        with mock.patch.object(m,'load',side_effect=lambda name:{'window':budget,'evidence':evidence,'lifecycle':self.lifecycle,'readiness':sampling}[name]),mock.patch.object(m,'Resources',return_value=resource),mock.patch.object(m,'bind_unit_test_host',side_effect=bind),mock.patch.object(self.lifecycle.Run,'command',new=command),mock.patch.object(self.lifecycle,'stop_group',side_effect=close),mock.patch.object(subprocess,'Popen',side_effect=spawn),mock.patch.object(signal,'signal'),mock.patch.object(time,'monotonic',side_effect=lambda:clock[0]),mock.patch.object(time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)),mock.patch.object(Path,'home',return_value=self.root/'home'),mock.patch.object(os,'uname',return_value=SimpleNamespace(machine='arm64')):
            result=m.worker(90,context)
        metadata=json.loads((self.scope/'metadata.json').read_bytes())
        self.assertFalse(any(row[:3]==['xcrun','simctl','install'] for row in self.commands))
        if profile_rejected:
            self.assertEqual(result,1)
            self.assertFalse(any(row[:2]==['xcodebuild','test-without-building'] for row in self.commands))
            self.assertFalse(any(row[:3]==['xcrun','simctl','create'] for row in self.commands))
            self.assertFalse((self.scope/'compiled-host-before.json').exists())
            self.assertEqual(metadata['native_phase_deadlines_seconds'],m.NATIVE_PHASES)
            return result,metadata
        self.assertEqual(sum(row[:2]==['xcodebuild','test-without-building'] for row in self.commands),1)
        self.assertFalse((self.scope/'installed-before.json').exists())
        self.assertTrue((self.scope/'compiled-host-before.json').exists())
        self.assertEqual(metadata['installation_contract']['installer'],'xcodebuild test-without-building')
        self.assertFalse(metadata['installation_contract']['prelaunch_installed_snapshot'])
        self.assertEqual(metadata['cleanup'],{'shutdown':0,'delete':0});self.assertTrue(metadata['device_removed'])
        self.assertEqual(metadata['native_phase_deadlines_seconds'],m.NATIVE_PHASES)
        return result,metadata
    def test_late_first_case_still_fails_at_original300_and_cleans_up(self):
        result,metadata=self.exercise(start_case_after=350)
        self.assertEqual(result,1);self.assertEqual(metadata['native_storekit_tests'],0)
        self.assertEqual(self.lookup_count,0);self.assertTrue(metadata['device_removed'])
        command=next(row for row in metadata['commands'] if row['args'][:2]==['xcodebuild','test-without-building'])
        self.assertEqual(command['timeout_seconds'],300)
        self.assertEqual(command['startup_observation']['status'],'UNAVAILABLE_WNOWAIT')
        self.assertTrue(command['owned_group_absent'])
    def test_early_completion_does_not_start_observation(self):
        result,metadata=self.exercise()
        self.assertEqual(result,0)
        command=next(row for row in metadata['commands'] if row['args'][:2]==['xcodebuild','test-without-building'])
        self.assertNotIn('startup_observation',command)
    def test_case_arriving_during_observation_is_read_even_if_child_exits(self):
        result,metadata=self.exercise(start_case_after=280,case_during_observation=True)
        self.assertEqual(self.sample_calls,1);self.assertEqual(result,0)
        self.assertEqual(metadata['native_storekit_tests'],8)
        self.assertEqual(metadata['first_started_native_case'],'ProStoreTests/'+self.m.CASE_NAMES[0])
        self.assertTrue(metadata['installed_after_exact_baseline'])
    def test_one_install_authority_first_capture_after_real_start_and_exact_after(self):
        result,metadata=self.exercise();self.assertEqual(result,0)
        during=json.loads((self.scope/'installed-during.json').read_bytes());after=json.loads((self.scope/'installed-after.json').read_bytes())
        self.assertEqual(during['comparison_basis'],'compiled_host');self.assertEqual(during['observation'],'first_after_actual_test_start')
        self.assertEqual(after['comparison_basis'],'first_installed_snapshot');self.assertEqual(after['expected_container_path'],during['path'])
        self.assertTrue(after['exact_container_path']);self.assertTrue(after['accepted_identity'])
        self.assertEqual(after['files'],during['files']);self.assertEqual(metadata['first_started_native_case'],'ProStoreTests/'+self.m.CASE_NAMES[0])
        self.assertTrue(metadata['explicit_inert_unit_host_observed']);self.assertEqual(metadata['native_storekit_tests'],8)
        self.assertTrue(metadata['compiled_host_unchanged']);self.assertTrue(metadata['source_and_compiled_host_unchanged'])
    def test_missing_actual_case_start_cannot_capture_or_accept(self):
        result,metadata=self.exercise(start_case=False);self.assertEqual(result,1)
        self.assertEqual(self.lookup_count,0);self.assertNotIn('first_installed_snapshot',metadata)
        self.assertFalse((self.scope/'installed-during.json').exists());self.assertFalse((self.scope/'installed-after.json').exists())
        self.assertEqual(metadata['result'],'failed');self.assertTrue(metadata['failures'])
        progress=metadata['native_failure_progress']
        self.assertEqual(progress['status'],'missing_staging')
        self.assertTrue(progress['stdout_markers']['inert_host_observed'])
        self.assertIsNone(progress['stdout_markers']['first_case_start_observed'])
        self.assertGreater(progress['stdout_markers']['log_bytes_examined'],0)
    def test_old_toolchain_is_rejected_before_native_spawn(self):
        self.toolchain='Xcode 16.4\nBuild version 16F6'
        result,_=self.exercise(profile_rejected=True);self.assertEqual(result,1)
        self.assertFalse(any(row[:2]==['xcodebuild','test-without-building'] for row in self.commands))
    def test_old_runtime_is_rejected_before_native_spawn(self):
        self.runtime_identifier='com.apple.CoreSimulator.SimRuntime.iOS-18-5';self.runtime_version='18.5'
        result,_=self.exercise(profile_rejected=True);self.assertEqual(result,1)
        self.assertFalse(any(row[:2]==['xcodebuild','test-without-building'] for row in self.commands))
    def test_wrong_runtime_version_is_rejected_before_native_spawn(self):
        self.runtime_version='18.5'
        result,_=self.exercise(profile_rejected=True);self.assertEqual(result,1)
        self.assertFalse(any(row[:2]==['xcodebuild','test-without-building'] for row in self.commands))
    def test_cross_toolchain_host_is_rejected_before_native_spawn(self):
        path=self.host/'Info.plist';info=plistlib.loads(path.read_bytes());info['DTXcodeBuild']='16F6';path.write_bytes(plistlib.dumps(info))
        result,_=self.exercise(profile_rejected=True);self.assertEqual(result,1)
        self.assertFalse(any(row[:2]==['xcodebuild','test-without-building'] for row in self.commands))
    def test_changed_container_with_identical_files_is_saved_and_rejected(self):
        result,metadata=self.exercise(changed_container=True);self.assertEqual(result,1)
        after=json.loads((self.scope/'installed-after.json').read_bytes())
        self.assertTrue(after['exact_payload']);self.assertFalse(after['exact_container_path']);self.assertFalse(after['accepted_identity'])
        self.assertNotIn('installed_after_exact_baseline',metadata)
    def test_changed_bytes_after_first_capture_are_saved_and_rejected(self):
        result,metadata=self.exercise(changed_bytes=True);self.assertEqual(result,1)
        after=json.loads((self.scope/'installed-after.json').read_bytes())
        self.assertTrue(after['exact_container_path']);self.assertFalse(after['exact_payload']);self.assertFalse(after['accepted_identity'])
        self.assertEqual(after['differences'][0]['fields'],['sha256'])
    def test_actual_case_start_parser_rejects_suite_completion_unknown_and_partial_rows(self):
        name=self.m.CASE_NAMES[0];line=("Test Case '-[CleanSendTests.ProStoreTests "+name+"]' started.").encode()
        self.assertEqual(self.m.observed_native_case_start(line),'ProStoreTests/'+name)
        for raw in (b"Test Suite 'ProStoreTests' started.",line.replace(b'started',b'passed'),line.replace(name.encode(),b'testUnknown'),line.replace(b'CleanSendTests',b'OtherTests'),line[:-1],b'command selector '+line):
            self.assertIsNone(self.m.observed_native_case_start(raw))



class NativeStartupObservationTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_startup_observation',DRIVER)
        self.r=self.m.load('readiness')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.m.SCOPE=Path(self.tmp.name);self.m.ROOT=self.m.SCOPE
        self.clock=[225.0];self.events=[]
        self.run=SimpleNamespace(meta={'commands':[]},persist=lambda:self.events.append('persist'))
        self.proc=SimpleNamespace(pid=999,returncode=None,
            poll=mock.Mock(side_effect=AssertionError('must not reap target')),
            wait=mock.Mock(side_effect=AssertionError('must not reap target')))
        self.item={};self.calls=[]
        def observe(proc):self.events.append('owned');return False
        def command(args,name,deadline,out,env,cwd,rows,*,run):
            self.calls.append((args,name,deadline));self.events.append('observation')
            self.clock[0]+=1
            row={'kind':'diagnostic','status':'RETURNED','returncode':0,'owned_group_absent':True}
            rows.append(row);run.meta['commands'].append(row)
        self.command=command
        patches=(mock.patch.object(self.m,'load',return_value=self.r),
            mock.patch.object(self.r,'supported',return_value=True),
            mock.patch.object(self.r,'observe_owned',side_effect=observe),
            mock.patch.object(self.r,'command',side_effect=command),
            mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]))
        for patch in patches:patch.start();self.addCleanup(patch.stop)
    def observation(self,end=300,case=None):
        return self.m.observe_native_startup(self.run,self.proc,self.item,0,end,case,{})
    def test_trigger_is_one_shot_and_preserves_exact_deadline(self):
        self.assertTrue(self.observation());self.assertFalse(self.observation())
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][2],230)
        self.assertLess(self.events.index('owned'),self.events.index('observation'))
        self.assertEqual(self.calls[0][0],['/bin/ps','-p','999','-o','pid=,ppid=,pgid=,stat=,pcpu=,time=,wchan=,comm='])
        self.proc.poll.assert_not_called();self.proc.wait.assert_not_called()
        self.assertNotIn('native_storekit_tests',self.run.meta)
    def test_initial_persistence_does_not_renew_five_second_window(self):
        count=[0]
        def persist():
            count[0]+=1
            if count[0]==1:self.clock[0]+=3
        self.run.persist=persist
        self.assertTrue(self.observation());self.assertEqual(self.calls[0][2],230)
    def test_early_or_real_case_start_never_launches_observer(self):
        self.clock[0]=224.999;self.assertFalse(self.observation())
        self.clock[0]=225;self.assertFalse(self.observation(case='ProStoreTests/testActual'))
        self.run.meta['first_started_native_case']='ProStoreTests/testActual'
        self.assertFalse(self.observation());self.assertEqual(self.calls,[])
    def test_already_exited_child_is_not_observationd(self):
        with mock.patch.object(self.r,'observe_owned',return_value=True):self.assertTrue(self.observation())
        self.assertEqual(self.item['startup_observation']['status'],'NOT_STARTED_CHILD_EXITED');self.assertEqual(self.calls,[])
    def test_lost_direct_child_reservation_never_observees(self):
        with mock.patch.object(self.r,'observe_owned',side_effect=self.r.OwnershipLost('gone')):
            with self.assertRaises(self.r.OwnershipLost):self.observation()
        self.assertTrue(self.item['ownership_lost']);self.assertFalse(self.item['owned_group_absent'])
        self.assertEqual(self.calls,[])
    def test_missing_wnowait_is_explicitly_unavailable(self):
        with mock.patch.object(self.r,'supported',return_value=False):self.assertTrue(self.observation())
        self.assertEqual(self.item['startup_observation']['status'],'UNAVAILABLE_WNOWAIT');self.assertEqual(self.calls,[])
    def test_short_original_budget_is_not_extended(self):
        self.assertTrue(self.observation(end=227));self.assertEqual(self.calls,[])
        self.assertEqual(self.item['startup_observation']['status'],'NOT_STARTED_DEADLINE')
        self.item={};self.assertTrue(self.observation(end=228));self.assertEqual(self.calls[0][2],228)
    def test_existing_observation_path_is_never_overwritten(self):
        (self.m.SCOPE/'native-startup-process.txt').write_bytes(b'unique')
        with self.assertRaises(self.r.CleanupUnknown):self.observation()
        self.assertEqual(self.calls,[]);self.assertEqual((self.m.SCOPE/'native-startup-process.txt').read_bytes(),b'unique')
    def test_unavailable_observation_is_diagnostic_only(self):
        def unavailable(args,name,deadline,out,env,cwd,rows,*,run):
            row={'kind':'diagnostic','status':'UNAVAILABLE','error':'OSError'};rows.append(row);run.meta['commands'].append(row)
        with mock.patch.object(self.r,'command',side_effect=unavailable):self.assertTrue(self.observation())
        self.assertEqual(self.item['startup_observation']['status'],'UNAVAILABLE')
        self.assertNotIn('native_storekit_tests',self.run.meta)
    def test_unknown_cleanup_stays_fatal_even_with_later_esrch(self):
        def failed(*args,**kwargs):
            self.run.meta['commands'].append({'kind':'diagnostic','owned_process_group':998,'owned_group_absent':False})
            self.run.meta['diagnostic_cleanup_unconfirmed']=True
            raise self.r.CleanupUnknown('unknown')
        with mock.patch.object(self.r,'command',side_effect=failed):
            with self.assertRaises(self.r.CleanupUnknown):self.observation()
        def missing(*args):raise ProcessLookupError()
        result=self.m.aggregate_command_groups(self.run.meta,0,clock=lambda:226,probe=missing)
        self.assertFalse(result['all_absent']);self.assertFalse(result['groups'][0]['absent'])
    def test_ownership_loss_is_not_inferred_away_by_absence_probe(self):
        row={'owned_process_group':999,'owned_group_absent':False,'ownership_lost':True}
        probe=mock.Mock(side_effect=ProcessLookupError())
        result=self.m.aggregate_command_groups({'commands':[row]},0,clock=lambda:226,probe=probe)
        self.assertFalse(result['all_absent']);probe.assert_not_called()
    def test_pre_pid_diagnostic_obligation_is_not_lost(self):
        result=self.m.aggregate_command_groups({'commands':[{'kind':'diagnostic','owned_group_absent':False}],
            'diagnostic_cleanup_unconfirmed':True},0,clock=lambda:226,probe=mock.Mock())
        self.assertFalse(result['all_absent'])
    def test_observation_output_cannot_satisfy_actual_test_log(self):
        fake=("Test Case '-[CleanSendTests.ProStoreTests "+self.m.CASE_NAMES[0]+"]' started.\n").encode()
        (self.m.SCOPE/'native-startup-process.txt').write_bytes(fake)
        tail,count,host,case=self.m.read_native_output(io.BytesIO(b''),b'',0,300)
        self.assertEqual(count,0);self.assertFalse(host);self.assertIsNone(case)
    def test_test_log_byte_cap_and_io_failure_remain_fatal(self):
        with self.assertRaises(AssertionError):self.m.read_native_output(io.BytesIO(b'x'),b'',16*2**20,300)
        with self.assertRaises(OSError):self.m.read_native_output(SimpleNamespace(read=mock.Mock(side_effect=OSError('read'))),b'',0,300)

    def test_log_drain_finds_case_after_first_chunk_and_retains_it_after_tail_rotates(self):
        case=("Test Case '-[CleanSendTests.ProStoreTests "+self.m.CASE_NAMES[0]+"]' started.\n").encode()
        raw=b'x'*65536+b'\n'+case+b'y'*262144
        tail,count,host,observed=self.m.read_native_output(io.BytesIO(raw),b'',0,300)
        self.assertEqual(count,len(raw));self.assertEqual(observed,'ProStoreTests/'+self.m.CASE_NAMES[0])
        self.assertLessEqual(len(tail),131072);self.assertNotIn(case,tail)
        self.assertFalse(self.observation(case=observed));self.assertEqual(self.calls,[])
    def test_log_drain_never_extends_deadline(self):
        reader=mock.Mock()
        with self.assertRaises(AssertionError):self.m.read_native_output(reader,b'',0,225)
        reader.read.assert_not_called()
        def slow_read(size):self.clock[0]=301;return b'x'
        with self.assertRaises(AssertionError):self.m.read_native_output(SimpleNamespace(read=slow_read),b'',0,300)

class NativeObservationCommandTests(unittest.TestCase):
    def setUp(self):
        self.m=load('native_observation_command',DRIVER);self.r=self.m.load('readiness')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.clock=[100.0]
        self.run=SimpleNamespace(meta={'commands':[]},persist=lambda:None)
    def test_expired_observer_slice_stops_before_spawn(self):
        rows=[]
        with mock.patch.object(self.r,'supported',return_value=True),mock.patch.object(subprocess,'Popen') as spawn:
            self.r.command(['/bin/ps','-p','999','-o','pid='],'command.txt',time.monotonic()-1,self.root,{},self.root,rows,run=self.run)
        spawn.assert_not_called();self.assertEqual(rows[0]['status'],'NOT_STARTED_DEADLINE')
    def test_real_diagnostic_helper_records_spawn_failure_without_payload_execution(self):
        rows=[]
        with mock.patch.object(self.r,'supported',return_value=True),mock.patch.object(subprocess,'Popen',side_effect=OSError('cannot spawn')):
            self.r.command(['/bin/ps','-p','999','-o','pid='],'command.txt',time.monotonic()+5,self.root,{},self.root,rows,run=self.run)
        self.assertEqual(rows[0]['status'],'UNAVAILABLE');self.assertEqual(rows[0]['error'],'OSError')
        self.assertFalse(self.run.meta['diagnostic_cleanup_unconfirmed'])
    def test_real_diagnostic_helper_hang_uses_shared_five_second_budget_and_cleans(self):
        proc=SimpleNamespace(pid=998,returncode=None);rows=[];closed=[]
        def stop(p,deadline,row):
            self.assertIs(p,proc);closed.append(deadline);self.clock[0]=104
            row['cleanup_confirmed']=True;p.returncode=-15
        with mock.patch.object(self.r,'supported',return_value=True),mock.patch.object(subprocess,'Popen',return_value=proc),mock.patch.object(self.r,'observe_owned',return_value=False),mock.patch.object(self.r,'stop_observer',side_effect=stop),mock.patch.object(time,'monotonic',side_effect=lambda:self.clock[0]),mock.patch.object(time,'sleep',side_effect=lambda s:self.clock.__setitem__(0,self.clock[0]+s)):
            self.r.command(['/bin/ps','-p','999','-o','pid='],'command.txt',105,self.root,{},self.root,rows,run=self.run)
        self.assertEqual(rows[0]['status'],'TIMEOUT');self.assertEqual(closed,[105])
        self.assertTrue(rows[0]['owned_group_absent']);self.assertFalse(self.run.meta['diagnostic_cleanup_unconfirmed'])
        self.assertLess(self.clock[0],105)
    def test_observationr_cancellation_cleans_then_propagates_before_any_next_operation(self):
        proc=SimpleNamespace(pid=998,returncode=None);rows=[];closed=[]
        def stop(p,deadline,row):
            closed.append(p.pid);row['cleanup_confirmed']=True;p.returncode=-15
        with mock.patch.object(self.r,'supported',return_value=True),mock.patch.object(subprocess,'Popen',return_value=proc),mock.patch.object(self.r,'observe_owned',side_effect=InterruptedError('cancelled')),mock.patch.object(self.r,'stop_observer',side_effect=stop):
            with self.assertRaises(InterruptedError):
                self.r.command(['/bin/ps','-p','999','-o','pid='],'command.txt',time.monotonic()+5,self.root,{},self.root,rows,run=self.run)
        self.assertEqual(closed,[998]);self.assertTrue(rows[0]['owned_group_absent'])
        self.assertFalse(self.run.meta['diagnostic_cleanup_unconfirmed'])
        self.assertNotIn('native_storekit_tests',self.run.meta)
    @unittest.skipUnless(hasattr(os,'waitid') and hasattr(os,'WNOWAIT'),'requires non-reaping child observation')
    def test_direct_child_that_exits_during_observation_remains_reserved_until_return(self):
        child='import select,sys; ready,_,_=select.select([sys.stdin],[],[],5); sys.stdin.read(1) if ready else None'
        proc=subprocess.Popen([sys.executable,'-B','-c',child],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.m.SCOPE=self.root;self.m.ROOT=self.root;item={};observations=[]
        def inert_observation(args,name,deadline,out,env,cwd,rows,*,run):
            proc.stdin.write(b'x');proc.stdin.flush()
            end=time.monotonic()+2
            while not self.r.observe_owned(proc):
                self.assertLess(time.monotonic(),end);time.sleep(.01)
            observations.append(proc.returncode)
            rows.append({'kind':'diagnostic','status':'RETURNED','owned_group_absent':True})
        try:
            now=time.monotonic()
            with mock.patch.object(self.m,'load',return_value=self.r),mock.patch.object(self.r,'command',side_effect=inert_observation):
                self.assertTrue(self.m.observe_native_startup(self.run,proc,item,now-225,now+5,None,{}))
            self.assertEqual(observations,[None]);self.assertIsNone(proc.returncode)
            self.assertTrue(self.r.observe_owned(proc));self.assertEqual(proc.wait(timeout=2),0)
        finally:
            try:proc.stdin.close()
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    try:proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)


class NativeCohortWorkflowTests(unittest.TestCase):
    def test_only_native_job_overrides_toolchain_and_builds_own_products(self):
        workflow=(ROOT/'.github/workflows/ci.yml').read_text()
        prefix,native=workflow.split('  native-storekit:\n',1)
        native,suffix=native.split('  package-smoke:\n',1)
        self.assertIn('env:\n  DEVELOPER_DIR: /Applications/Xcode_16.4.app/Contents/Developer',prefix)
        self.assertIn('    env:\n      DEVELOPER_DIR: /Applications/Xcode_26.3.app/Contents/Developer',native)
        self.assertEqual(workflow.count('DEVELOPER_DIR:'),2)
        self.assertIn('Xcode 26.3\\nBuild version 17C529',native)
        self.assertNotIn('16F6',native)
        self.assertIn('-configuration Debug -sdk iphonesimulator26.2',native)
        self.assertIn('-derivedDataPath .derivedData',native)
        self.assertIn('xcodebuild build-for-testing -project CleanSend.xcodeproj',native)
        self.assertLess(native.index('xcodebuild build-for-testing'),native.index('python3 -B scripts/check-native-storekit.py'))
        self.assertNotIn('download-artifact',native)
        self.assertIn('Xcode 16.4\\nBuild version 16F6',prefix)
        self.assertIn('Xcode 16.4\\nBuild version 16F6',suffix)
        self.assertNotIn('DEVELOPER_DIR:',suffix)
        self.assertIn("host=ROOT/'.derivedData/Build/Products/Debug-iphonesimulator/CleanSend.app'",DRIVER.read_text())

def setitem(mapping,key,value):mapping[key]=value

if __name__=='__main__':unittest.main()
