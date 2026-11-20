"""Fault-injection tests. No game, Wine, USB or network access."""
from pathlib import Path
import configparser
import codecs
import errno
import fcntl
import json
import os
import signal
import socket
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, copy_private, ini_set, decode_text, DEFAULT_SETTINGS
import runtime
import compatibility
import startup_checks
from diagnostics import collect


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'private')
        self.root=self.store.root/'Games'/('a'*32)
        self.package=self.root/'HDD/Package';self.package.mkdir(parents=True)
        self.game=dict(id='a'*32,packagePath=str(self.package),sourcePath='/source',ready=True,settings=dict(DEFAULT_SETTINGS))
        self.store.update(self.game)
        (self.package/'mai2.ini').write_text('[Sound]\nSound8Ch=1\n')
        (self.package/'segatools.ini').write_text('[vfs]\namfs=amfs\nappdata=appdata\noption=options\n')
        self.session=self.root/'Sessions/20261108-010000-123456';self.session.mkdir(parents=True)
    def tearDown(self):self.temp.cleanup()

    def testOldSettingsReceiveNewDefaultsWithoutResettingValues(self):
        self.game['settings']={'width':720,'height':1280,'metalHUD':False}
        self.store.update(self.game)
        settings=Store(self.store.root).get(self.game['id'])['settings']
        self.assertEqual(set(settings),set(DEFAULT_SETTINGS))
        self.assertEqual((settings['width'],settings['height'],settings['metalHUD']),(720,1280,False))

    def testReadOnlySourceProducesWritablePrivateCopy(self):
        source=Path(self.temp.name)/'readonly';source.write_bytes(b'original');source.chmod(0o400)
        target=Path(self.temp.name)/'copy';copy_private(source,target)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        target.write_bytes(b'edited');self.assertEqual(source.read_bytes(),b'original')

    @unittest.skipUnless(hasattr(os,'chflags'),'BSD file locks require macOS')
    def testAPFSCloneOfLockedAndAppendOnlyFilesDoesNotLockThePrivateCopy(self):
        for flag in [stat.UF_IMMUTABLE,stat.UF_APPEND]:
            source=Path(self.temp.name)/('locked-'+str(flag));target=source.with_suffix('.copy')
            source.write_bytes(b'original');source.chmod(0o400);os.chflags(source,flag)
            try:
                copy_private(source,target)
                self.assertFalse(target.stat().st_flags & (stat.UF_IMMUTABLE | stat.UF_APPEND))
                self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
                target.write_bytes(b'changed')
                self.assertEqual(source.read_bytes(),b'original')
                self.assertEqual(source.stat().st_flags,flag)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode),0o400)
            finally:
                for path in [source,target]:
                    if path.exists():os.chflags(path,0)

    @unittest.skipUnless(hasattr(os,'chflags'),'BSD file locks require macOS')
    def testCrossVolumeFallbackCopiesDataWithoutInheritingImmutableMetadata(self):
        source=Path(self.temp.name)/'locked.dll';target=source.with_suffix('.copy')
        source.write_bytes(b'original');os.chflags(source,stat.UF_IMMUTABLE)
        try:
            with patch('storage.clone_private',side_effect=OSError(errno.EXDEV,'cross volume')):
                copy_private(source,target)
            self.assertEqual(target.read_bytes(),source.read_bytes())
            self.assertEqual(target.stat().st_mtime_ns,source.stat().st_mtime_ns)
            target.write_bytes(b'changed');self.assertEqual(source.read_bytes(),b'original')
            self.assertEqual(source.stat().st_flags,stat.UF_IMMUTABLE)
        finally:
            for path in [source,target]:
                if path.exists():os.chflags(path,0)

    def testInterruptedDataCopyRemovesOnlyItsPartialDestination(self):
        source=Path(self.temp.name)/'source';target=Path(self.temp.name)/'partial';source.write_bytes(b'original')
        def no_space(incoming,outgoing,*args):
            outgoing.write(b'partial');raise OSError(errno.ENOSPC,'no space')
        with patch('storage.clone_private',side_effect=OSError(errno.EXDEV,'cross volume')), \
                patch('storage.shutil.copyfileobj',side_effect=no_space):
            with self.assertRaises(OSError):copy_private(source,target)
        self.assertFalse(target.exists());self.assertEqual(source.read_bytes(),b'original')

    def testCopyRefusesExistingDestinationsAndSymlinkSourcesWithoutChangingThem(self):
        source=Path(self.temp.name)/'original';target=Path(self.temp.name)/'existing'
        source.write_bytes(b'original');target.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):copy_private(source,target)
        self.assertEqual(target.read_bytes(),b'existing')
        link=Path(self.temp.name)/'link';link.symlink_to(source)
        with self.assertRaises(ValueError):copy_private(link,Path(self.temp.name)/'unused')
        self.assertEqual(source.read_bytes(),b'original')

    def testNestedWindowsVfsUsesTheDirectoryWineWillActuallyRead(self):
        (self.package/'segatools.ini').write_text('[vfs]\namfs=data\\amfs\nappdata=data\\appdata\noption=options\n')
        compatibility.prepare_configuration(self.store,self.game)
        self.assertTrue((self.package/'data/amfs').is_dir())
        self.assertFalse((self.package/r'data\amfs').exists())
        self.assertEqual(compatibility.get(compatibility.ini(self.package/'segatools.ini'),'vfs','amfs'),'data/amfs')

    def testNativeIniHasUnicodeBomWithoutLosingCommentsOrValues(self):
        original='; 中文注释：目录配置\n[vfs]\namfs=amfs\nappdata=appdata\noption=options\n[custom]\nlabel=保留此值\n'
        (self.package/'segatools.ini').write_bytes(original.encode('utf-8'))
        (self.package/'mai2.ini').write_text('; 声音配置\n[Sound]\nSound8Ch=1\n')
        compatibility.prepare_configuration(self.store,self.game)
        for name in ['segatools.ini','mai2.ini']:
            data=(self.package/name).read_bytes()
            self.assertTrue(data.startswith(codecs.BOM_UTF16_LE))
            self.assertEqual(decode_text(data)[1],'utf-16')
        config=compatibility.ini(self.package/'segatools.ini')
        self.assertEqual(config['custom']['label'],'保留此值')
        self.assertIn('; 中文注释：目录配置',decode_text((self.package/'segatools.ini').read_bytes())[0])
        # A second launch must not create another encoding change/backup.
        before=(self.package/'segatools.ini').read_bytes()
        with patch.object(self.store,'replace_with_backup',wraps=self.store.replace_with_backup) as replace:
            compatibility.prepare_configuration(self.store,self.game)
        replace.assert_not_called()
        self.assertEqual((self.package/'segatools.ini').read_bytes(),before)

    def testTemporaryNativeSettingsRetainUnicodeEncodingAndRestoreExactly(self):
        compatibility.prepare_configuration(self.store,self.game)
        path=self.package/'segatools.ini';before=path.read_bytes();text,encoding=decode_text(before)
        updated=ini_set(text,'aime','enable','1').encode(encoding)
        self.store.apply_launch_configs(self.game,self.session,[('segatools.ini',updated)])
        self.assertTrue(path.read_bytes().startswith(codecs.BOM_UTF16_LE))
        self.assertEqual(compatibility.ini(path)['aime']['enable'],'1')
        self.store.restore_launch_configs(self.game)
        self.assertEqual(path.read_bytes(),before)

    def testDuplicateIniKeysCannotKeepAnEarlierConflictingValue(self):
        text=ini_set('[vfs]\namfs=wrong\n; keep\namfs=also-wrong\n','vfs','amfs','correct')
        cp=configparser.ConfigParser(strict=True);cp.read_string(text)
        self.assertEqual(cp['vfs']['amfs'],'correct');self.assertIn('; keep',text)

    def testCrossWorkerMutationLockRejectsCompetingOperation(self):
        other=Store(self.store.root)
        with self.store.operation():
            with self.store.operation():pass
            with self.assertRaisesRegex(ValueError,'任务'):
                with other.operation():self.fail('competing mutation entered')
        with other.operation():pass

    def testRepairCannotEnterWhileSessionOwnsThePrefix(self):
        with runtime.active_lease(self.store):
            with patch('runtime._prepare') as work, self.assertRaisesRegex(ValueError,'退出清理'):
                runtime.prepare(Store(self.store.root),Path('/no-runtime'),self.game['id'],lambda *_:None)
            work.assert_not_called()

    def testPidQueryFailureCannotPermitConfigWritesDuringLiveSession(self):
        other=Store(self.store.root)
        with runtime.active_lease(self.store),patch('runtime.session_status',return_value={'running':False}):
            with self.assertRaisesRegex(ValueError,'退出清理'):other.assert_stopped(self.game)

    def testNoWineServerToKillIsSuccessfulWhenWaitConfirmsExit(self):
        prefix=self.root/'Prefix';prefix.mkdir()
        with patch('runtime.subprocess.run',side_effect=[subprocess.CompletedProcess([],1),subprocess.CompletedProcess([],0)]) as run:
            runtime.stop_wine(Path('/runtime'),prefix)
        self.assertEqual(run.call_count,2)

    @unittest.skipUnless(sys.platform=='darwin','Seatbelt is macOS specific')
    def testUnicodeSeatbeltRuleActuallyAllowsWritingToItsOwnedDirectory(self):
        owned=(Path(self.temp.name)/'中文 用户 空格').resolve();owned.mkdir()
        target=owned/'test.txt'
        policy='(version 1)(allow default)(deny file-write*)(allow file-write* (subpath '+runtime.sandbox_path(owned)+'))'
        result=subprocess.run(['/usr/bin/sandbox-exec','-p',policy,'/usr/bin/touch',str(target)],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(target.is_file())

    def testCleanupFailureDoesNotSkipBridgeOrConfigurationRecovery(self):
        original=(self.package/'mai2.ini').read_bytes()
        self.store.apply_launch_configs(self.game,self.session,[('mai2.ini',b'temporary')])
        child=Mock();child.poll.return_value=None;stream=Mock();record={'phase':'running'}
        with patch('runtime.stop_wine',side_effect=subprocess.TimeoutExpired('wineserver',10)):
            runtime.cleanup_session(self.store,Path('/runtime'),self.game,self.session,record,None,[child],[stream])
        child.terminate.assert_called_once();stream.close.assert_called_once()
        self.assertEqual((self.package/'mai2.ini').read_bytes(),original)
        self.assertFalse((self.root/'launch-configs.json').exists())
        state=json.loads((self.root/'session.json').read_text())
        self.assertEqual(state['phase'],'error');self.assertIn('ended',state)
        self.assertTrue((self.session/'cleanup-error.log').is_file())

    def testPreparationFailureInvalidatesReadyAndStillStopsWine(self):
        with patch('runtime.stop_wine') as stop, patch('runtime._prepare',side_effect=RuntimeError('dependency failed')):
            with self.assertRaisesRegex(RuntimeError,'dependency failed'):
                runtime.prepare(self.store,Path('/runtime'),self.game['id'],lambda *_:None)
        self.assertFalse(self.store.get(self.game['id'])['ready']);self.assertEqual(stop.call_count,2)

    def testMissingBootstrapAndBadDaemonJsonBlockPreparation(self):
        (self.package/'config_common.json').write_text('[]')
        report=compatibility.inspect_package(self.package)
        self.assertIn('缺少 version.dll',report['issues'])
        self.assertIn('config_common.json 不是有效的 JSON 对象',report['issues'])
        self.assertFalse(report['canPrepare'])

    def testNoDisplayAndDisplayHelperTimeoutHaveActionableErrors(self):
        for response in [dict(return_value=b'[]'),dict(side_effect=subprocess.TimeoutExpired('inventory',8))]:
            with patch('runtime.subprocess.check_output',**response),self.assertRaisesRegex(RuntimeError,'显示器'):
                runtime.display_inventory(Path('/runtime'))

    def testDisconnectedDisplayFallsBackToAvailableMainScreen(self):
        main=dict(display_uuid='main',main=True,CG_frame=dict(width=1920,height=1080))
        self.assertEqual(runtime.select_display([main],'unplugged'),main)

    def testDeadManagerNeverRemainsInRunningPhase(self):
        (self.root/'session.json').write_text(json.dumps(dict(manager_pid=123,phase='running',message='游戏运行中',session=str(self.session))))
        with patch('runtime.os.kill',side_effect=ProcessLookupError):status=runtime.session_status(self.store,self.game)
        self.assertFalse(status['running']);self.assertEqual(status['phase'],'error')

    def testMicrosecondSessionsAndCleanupLogsAppearInDiagnostics(self):
        (self.session/'cleanup-error.log').write_text('wine timeout')
        snapshot=collect(self.store,self.game)
        self.assertEqual(snapshot['session'],self.session.name)
        self.assertTrue(any('wine timeout' in log['text'] for log in snapshot['logs']))

    def testChangedManagedAssemblyInvalidatesImportReuse(self):
        managed=self.package/'Sinmai_Data/Managed';managed.mkdir(parents=True)
        assembly=managed/'Assembly-CSharp.dll';assembly.write_bytes(b'old')
        before=compatibility.core_signature(self.package)
        assembly.write_bytes(b'new')
        self.assertNotEqual(before,compatibility.core_signature(self.package))

    def testOwnedDiagnosticsPluginsDoNotInvalidateSourceIdentity(self):
        before=compatibility.core_signature(self.package)
        mods=self.package/'Mods';mods.mkdir()
        (mods/'AirmaiBootTrace.dll').write_bytes(b'owned')
        self.assertEqual(before,compatibility.core_signature(self.package))

    def testMissingRosettaProducesAnExplicitPrerequisiteError(self):
        with patch('runtime.platform.system',return_value='Darwin'),patch('runtime.platform.machine',return_value='arm64'), \
                patch('runtime.subprocess.run',side_effect=OSError('Bad CPU type')),self.assertRaisesRegex(runtime.LaunchRequirement,'Rosetta 2'):
            runtime.host_preflight()

    def testStartupHttpsUsesSystemTrustWithoutHomebrewOrDisablingValidation(self):
        with patch('startup_checks.sys.platform','darwin'),patch.dict(os.environ,{'SSL_CERT_FILE':'/nonexistent/homebrew/ca.pem'}):
            context=startup_checks.tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(len(context.get_ca_certs()),0)

    def testMissingSavedNetworkInterfaceFallsBackToActiveAdapter(self):
        with patch('runtime.socket.if_nameindex',return_value=[(1,'lo0'),(2,'en0')]), \
                patch('runtime.subprocess.run',return_value=SimpleNamespace(stdout='inet 192.0.2.10\nstatus: active')):
            self.assertEqual(runtime.active_interface('en9'),'en0')

    def testAutomaticNetworkInterfacePrefersPhysicalDefaultRoute(self):
        def probe(command,**_):
            return SimpleNamespace(stdout='interface: en8\n' if command[0]=='/sbin/route' else 'inet 192.0.2.10\nstatus: active')
        with patch('runtime.socket.if_nameindex',return_value=[(1,'en0'),(2,'en8'),(3,'utun10')]), \
                patch('runtime.subprocess.run',side_effect=probe):
            self.assertEqual(runtime.active_interface(),'en8')
            self.assertEqual(runtime.active_interface('en0'),'en0')

    def testTemporarySystemDnsFailureUsesPublicFallback(self):
        answer=b'AB'+struct.pack('>HHHHH',0x8180,0,1,0,0)+b'\0'+struct.pack('>HHIH',1,1,60,4)+socket.inet_aton('192.0.2.42')
        with patch('runtime.socket.getaddrinfo',side_effect=socket.gaierror(socket.EAI_AGAIN,'temporary failure')), \
                patch('runtime.os.urandom',return_value=b'AB'),patch('runtime.socket.socket') as create_socket:
            udp=create_socket.return_value.__enter__.return_value
            udp.recv.return_value=answer
            self.assertEqual(runtime.resolve_ipv4('server.invalid'),('192.0.2.42',['192.0.2.42']))
            udp.connect.assert_called_once_with(('1.1.1.1',53))

    def testAuthRetainsTheSystemProxyRouteWhenAllPublicDnsServersFail(self):
        address='198.18.0.73'
        with patch('runtime.socket.getaddrinfo',return_value=[(0,0,0,'',(address,80))]), \
                patch('runtime.socket.if_nametoindex',return_value=9),patch('runtime.socket.socket') as create_socket:
            udp=create_socket.return_value.__enter__.return_value
            udp.recv.side_effect=socket.timeout('timed out')
            origin,addresses=runtime.resolve_ipv4('server.invalid','en8',allow_proxy_route=True)
            self.assertIsNone(origin)
            self.assertEqual(runtime.auth_routes(origin,addresses,'en8',False),[(address,'')])
            self.assertEqual(udp.connect.call_count,7)

    def testAuthOnlyFallsBackToUnboundOrdinaryRoutesInAutomaticMode(self):
        addresses=['198.18.0.73','192.0.2.42','192.0.2.43']
        direct=[('192.0.2.42','en8'),('192.0.2.43','en8')]
        proxy=[('198.18.0.73','')]
        self.assertEqual(runtime.auth_routes('192.0.2.42',addresses,'en8',True),direct+proxy)
        self.assertEqual(runtime.auth_routes('192.0.2.42',addresses,'en8',False),
                         direct+proxy+[('192.0.2.42',''),('192.0.2.43','')])

    def testDistinctConfiguredStartupAndDefaultServersKeepTheirRoles(self):
        (self.package/'segatools.ini').write_text('[DNS]\ndefault=default.invalid\nstartup=auth.invalid\n')
        (self.session/'relay-ready.json').write_text(json.dumps({'pid':123,'ready':True,'port':55002}))
        env={};relay=Mock(pid=123);relay.poll.return_value=None
        with patch('runtime.active_interface',return_value='en8'), \
                patch('runtime.resolve_ipv4',side_effect=[('192.0.2.42',['192.0.2.42','198.18.0.73']),('192.0.2.43',['192.0.2.43','198.18.0.74'])]) as resolve:
            runtime.configure_game_network(self.package,Path('/runtime'),self.game['settings'],self.session,env,Mock(return_value=relay))
        self.assertEqual([call.args[0] for call in resolve.call_args_list],['auth.invalid','default.invalid'])
        self.assertEqual(env['AIRMAIDX_AUTH_IPV4'],'192.0.2.42,198.18.0.73')
        self.assertEqual(env['AIRMAIDX_IP_MAP'],'198.18.0.74=192.0.2.43')

    def testAimeDnsFailureKeepsTheGameAuthRelayEnabled(self):
        (self.package/'segatools.ini').write_text('[DNS]\ndefault=auth.invalid\naimedb=aime.invalid\n')
        (self.session/'relay-ready.json').write_text(json.dumps({'pid':123,'ready':True,'port':55002}))
        env={}
        relay=Mock(pid=123);relay.poll.return_value=None
        with patch('runtime.active_interface',return_value='en8'), \
                patch('runtime.resolve_ipv4',side_effect=[('192.0.2.42',['192.0.2.42','198.18.0.73']),RuntimeError('DNS unavailable')]):
            runtime.configure_game_network(self.package,Path('/runtime'),self.game['settings'],self.session,env,Mock(return_value=relay))
        self.assertEqual(env['AIRMAIDX_TRANSPORT_FIX'],'1')
        self.assertEqual(env['AIRMAIDX_AUTH_IPV4'],'192.0.2.42,198.18.0.73')
        self.assertEqual(env['AIRMAIDX_RELAY_PORT'],'55002')
        self.assertNotIn('AIRMAIDX_IP_MAP',env)
        self.assertIn('Aime 地址解析失败',(self.session/'network-setup.log').read_text())

    def testRealSystemDnsAddressDoesNotUsePublicDnsFallback(self):
        with patch('runtime.socket.getaddrinfo',return_value=[(0,0,0,'',('192.0.2.42',80))]), \
                patch('runtime.socket.socket') as create_socket:
            self.assertEqual(runtime.resolve_ipv4('server.invalid','en1'),('192.0.2.42',['192.0.2.42']))
        create_socket.assert_not_called()

    def testBlockedPrimaryDnsFallsBackWhileKeepingThePhysicalInterface(self):
        answer=b'AB'+struct.pack('>HHHHH',0x8180,0,1,0,0)+b'\0'+struct.pack('>HHIH',1,1,60,4)+socket.inet_aton('192.0.2.42')
        with patch('runtime.socket.getaddrinfo',return_value=[(0,0,0,'',('198.18.0.73',80))]), \
                patch('runtime.os.urandom',return_value=b'AB'),patch('runtime.socket.if_nametoindex',return_value=9), \
                patch('runtime.socket.socket') as create_socket:
            udp=create_socket.return_value.__enter__.return_value
            udp.recv.side_effect=[socket.timeout('timed out'),answer]
            self.assertEqual(runtime.resolve_ipv4('server.invalid','en1'),('192.0.2.42',['192.0.2.42','198.18.0.73']))
        self.assertEqual([call.args[0] for call in udp.connect.call_args_list],[('1.1.1.1',53),('8.8.8.8',53)])
        self.assertEqual(udp.setsockopt.call_count,2)
        udp.setsockopt.assert_called_with(socket.IPPROTO_IP,25,9)
        self.assertTrue(all(call.args==(2,) for call in udp.settimeout.call_args_list))

    def testInvalidDnsRepliesAreSkippedAndExhaustionIsReported(self):
        with patch('runtime.socket.getaddrinfo',return_value=[(0,0,0,'',('198.18.0.73',80))]), \
                patch('runtime.socket.socket') as create_socket:
            udp=create_socket.return_value.__enter__.return_value
            udp.recv.side_effect=[b'',b'broken']+[socket.timeout('timed out')]*5
            with self.assertRaisesRegex(RuntimeError,'223.6.6.6'):
                runtime.resolve_ipv4('server.invalid')
        self.assertEqual(udp.connect.call_count,7)
        udp.setsockopt.assert_not_called()

    def testDnsFallbackCanReachTheLastBackup(self):
        answer=b'AB'+struct.pack('>HHHHH',0x8180,0,1,0,0)+b'\0'+struct.pack('>HHIH',1,1,60,4)+socket.inet_aton('192.0.2.42')
        with patch('runtime.socket.getaddrinfo',return_value=[(0,0,0,'',('198.18.0.73',80))]), \
                patch('runtime.os.urandom',return_value=b'AB'),patch('runtime.socket.socket') as create_socket:
            udp=create_socket.return_value.__enter__.return_value
            udp.recv.side_effect=[socket.timeout('timed out')]*6+[answer]
            self.assertEqual(runtime.resolve_ipv4('server.invalid')[0],'192.0.2.42')
        self.assertEqual([call.args[0][0] for call in udp.connect.call_args_list],
                         ['1.1.1.1','8.8.8.8','223.5.5.5','119.29.29.29','1.0.0.1','8.8.4.4','223.6.6.6'])
        self.assertTrue(all(call.args==(2,) for call in udp.settimeout.call_args_list))

    def testOptionalDnsFailureStillReachesGameLaunchAndRestoresConfigs(self):
        self.game['settings'].update(networkEnabled=True,hdxEnabled=False,mouseEnabled=False);self.store.update(self.game)
        drive=self.root/'Prefix/drive_c';drive.mkdir(parents=True)
        (self.package/'segatools.ini').write_text('[dns]\ndefault=server.invalid\n[vfs]\namfs=amfs\n')
        original=(self.package/'segatools.ini').read_bytes()
        fake=Mock();fake.poll.return_value=0;fake.returncode=0;fake.pid=123
        screen=dict(display_uuid='main',main=True,CG_frame=dict(x=0,y=0,width=1920,height=1080))
        with patch('controller_devices.inventory',return_value=dict(devices=[],errors=[])), \
                patch('runtime.display_inventory',return_value=[screen]),patch('runtime.active_interface',return_value='en0'), \
                patch('runtime.resolve_ipv4',side_effect=socket.gaierror('offline')),patch('startup_checks.discover',return_value=[]), \
                patch('runtime.stop_wine'),patch('runtime.subprocess.run',return_value=SimpleNamespace(returncode=0)), \
                patch('runtime.subprocess.Popen',return_value=fake) as launch:
            runtime.session_run(self.store,Path('/self-authored-test-runtime'),self.game['id'])
        launch.assert_called_once()
        state=json.loads((self.root/'session.json').read_text());session=Path(state['session'])
        self.assertTrue((session/'network-setup.log').exists())
        self.assertFalse((session/'service-error.log').exists())
        self.assertEqual((self.package/'segatools.ini').read_bytes(),original)
        # Exiting before any title evidence, including exit code 0, is a failure.
        self.assertEqual(state['phase'],'error')

    def testADXLaunchUsesTemporaryNativeConfigAndRestoresImportedValues(self):
        import base64
        from controller_protocols import select_endpoints
        row=dict(id='100',vendor=0x2e3c,product=0x5751,name='NPro fixture',usagePage=0xff00,usage=1,
                 descriptor=base64.b64encode(bytes.fromhex('0600ff0901a101750895088102c0')).decode())
        candidate=select_endpoints([row])[0]
        self.game['settings'].update(hdxEnabled=False,adxEnabled=True);self.store.update(self.game)
        drive=self.root/'Prefix/drive_c';drive.mkdir(parents=True)
        mods=self.package/'Mods';mods.mkdir()
        aqua=self.package/'AquaMai.toml';aqua.write_text('[GameSystem.AdxHidInput]\nDisabled = false\n')
        original=aqua.read_bytes()
        helper_root=Path(self.temp.name)/'runtime/helpers';helper_root.mkdir(parents=True)
        (helper_root/'AirmaiControllerInput.dll').write_bytes(b'owned helper fixture')
        (helper_root/'AirmaiMouseInput.dll').write_bytes(b'owned mouse fixture')
        bridge=Mock();bridge.poll.return_value=None;bridge.pid=123
        game_process=Mock();game_process.poll.return_value=0;game_process.returncode=0;game_process.pid=124
        def launch(command,**kwargs):
            if '--controller-input' in command:
                out=Path(command[-1]);out.mkdir()
                (out/'status.json').write_text('{"ready":true}')
                return bridge
            return game_process
        screen=dict(display_uuid='main',main=True,CG_frame=dict(x=0,y=0,width=1920,height=1080))
        with patch('controller_devices.inventory',return_value=dict(devices=[candidate],errors=[])), \
                patch('controller_devices.game_api_verified',return_value=True), \
                patch('runtime.display_inventory',return_value=[screen]),patch('startup_checks.discover',return_value=[]), \
                patch('runtime.stop_wine'),patch('runtime.subprocess.run',return_value=SimpleNamespace(returncode=0)), \
                patch('runtime.subprocess.Popen',side_effect=launch) as start, \
                patch.object(self.store,'apply_launch_configs',wraps=self.store.apply_launch_configs) as apply:
            runtime.session_run(self.store,helper_root.parent,self.game['id'])
        self.assertEqual(start.call_count,2)
        changes=dict(apply.call_args.args[2])
        self.assertIn(b'DummyTouchPanel=0',changes['mai2.ini'])
        self.assertIn(b'Disabled=true',changes['AquaMai.toml'])
        self.assertIn(b'felicaGen=0',changes['segatools.ini'])
        self.assertEqual(aqua.read_bytes(),original)
        record=json.loads((self.root/'session.json').read_text())
        # Until the game receiver has registered its providers and fresh input,
        # the mouse remains available even though the host HID opened.
        self.assertEqual(record['input_mode'],'mouse')
        report=json.loads((Path(record['session'])/'input-detection.json').read_text())
        self.assertEqual(report['mode'],'mouse')
        bridge.terminate.assert_called_once()

    def testPhoneReaderKeepsHDXTouchAndLEDAndRestoresHDDConfig(self):
        self.game['settings'].update(phoneReaderEnabled=True,hdxEnabled=True,mouseEnabled=False,networkEnabled=False)
        self.store.update(self.game)
        drive=self.root/'Prefix/drive_c';drive.mkdir(parents=True)
        (self.root/'Prefix/dosdevices').mkdir()
        (self.package/'Mods').mkdir()
        common=self.package/'config_common.json'
        original=json.dumps(dict(aime=dict(enable=False,unit=[dict(port=8)])))
        common.write_text(original)
        helper=self.store.root/'test-runtime/helpers';helper.mkdir(parents=True)
        for name in ['AirmaiHdxNativeTouch.dll','AirmaiHdxNativeLed.dll']:(helper/name).write_bytes(b'test helper')
        bridge=Mock();bridge.poll.return_value=None;bridge.pid=123
        fake=Mock();fake.poll.return_value=0;fake.returncode=0;fake.pid=124
        def launch(command,**kwargs):
            self.assertNotIn('--hdx-reader',command)
            if '--hdx-touch' in command or '--hdx-led' in command:
                folder=Path(command[-1]);folder.mkdir()
                (folder/'status.json').write_text('{"healthy":true,"native_port_open":true}')
                return bridge
            self.assertTrue((drive/'AirmaiPhoneReader.cfg').exists())
            return fake
        screen=dict(display_uuid='main',main=True,CG_frame=dict(x=0,y=0,width=1920,height=1080))
        with patch('runtime.detect_hdx',return_value=(['/dev/test-touch','/dev/test-led','/dev/test-reader'],{})), \
                patch('controller_devices.inventory',return_value=dict(devices=[],errors=[])), \
                patch('controller_devices.game_api_verified',return_value=True),patch('runtime.display_inventory',return_value=[screen]), \
                patch('startup_checks.discover',return_value=[]),patch('runtime.stop_wine'), \
                patch('runtime.subprocess.run',return_value=SimpleNamespace(returncode=0)), \
                patch('runtime.subprocess.Popen',side_effect=launch), \
                patch.object(self.store,'apply_launch_configs',wraps=self.store.apply_launch_configs) as apply:
            runtime.session_run(self.store,helper.parent,self.game['id'])
        changes=dict(apply.call_args.args[2]);seg=changes['segatools.ini'].decode()
        self.assertIn('aimeio',seg);self.assertIn(r'C:\AirmaiPhoneReader.dll',seg)
        self.assertIn('enable=1',seg);self.assertIn('felicaGen=0',seg)
        self.assertIn(b'DummyTouchPanel=0',changes['mai2.ini'])
        self.assertTrue(json.loads(changes['config_common.json'])['aime']['enable'])
        self.assertEqual(common.read_text(),original)
        self.assertFalse((drive/'AirmaiPhoneReader.cfg').exists())
        self.assertTrue((self.package/'Mods/AirmaiHdxNativeTouch.dll').exists())
        self.assertTrue((self.package/'Mods/AirmaiHdxNativeLed.dll').exists())
        self.assertFalse((self.root/'Prefix/dosdevices/com1').exists())

if __name__=='__main__':unittest.main()
