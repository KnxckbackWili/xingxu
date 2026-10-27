#!/usr/bin/env python3
"""Explicit, isolated loopback drill; never run this heavyweight probe in CI.

Requires a pre-created EMPTY PostgreSQL database named *_t25_stream.
The only retained artifacts are the JSON measurements and private temp paths.
"""
import argparse,hashlib,json,os,resource,socket,subprocess,sys,tempfile,time,threading
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database-url',required=True)
    parser.add_argument('--size',type=int,default=2*1024**3);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not args.database_url.endswith('_t25_stream') or not args.database_url.startswith('postgresql'):
        raise SystemExit('Requires a dedicated *_t25_stream PostgreSQL database')
    import psycopg2
    url=args.database_url.replace('postgresql+psycopg2://','postgresql://')
    with psycopg2.connect(url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            if cur.fetchone()[0]:raise SystemExit('Drill database must be empty; refusing to modify existing tables')
    root=Path(tempfile.mkdtemp(prefix='agvm-t25-real-stream-'));data=root/'data';data.mkdir(mode=0o700)
    source=root/'original.bin';block=hashlib.shake_256(b'xingxu-t25-real-source-v1').digest(1024**2)
    digest=hashlib.sha256();remaining=args.size
    with source.open('wb') as handle:
        while remaining:
            part=block[:min(remaining,len(block))];handle.write(part);digest.update(part);remaining-=len(part)
        handle.flush();os.fsync(handle.fileno())
    sha=digest.hexdigest()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'DATA_DIR':str(data),'DATABASE_URL':args.database_url,'SCHEDULER_ENABLED':'0','SEED_DEMO_USERS':'1',
        'MAX_UPLOAD_MB':'2048','TRUSTED_HOSTS':'127.0.0.1,localhost','AGVPM_ENABLE_CACHE':'0'}
    backend=Path(__file__).resolve().parents[1];log=(root/'server.log').open('wb')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],
        cwd=backend,env=env,stdout=log,stderr=subprocess.STDOUT)
    rss=[];stop=threading.Event()
    def sample():
        while not stop.wait(.1):
            try:rss.append(int(subprocess.check_output(['ps','-o','rss=','-p',str(server.pid)]).strip())*1024)
            except (ValueError,subprocess.CalledProcessError):pass
    thread=threading.Thread(target=sample,daemon=True);thread.start();began=time.monotonic()
    def check(response,status=200):
        if response.status_code!=status:raise AssertionError(f'{response.status_code}: {response.text[:1000]}')
        return response.json()
    try:
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=300)
        for _ in range(300):
            if server.poll() is not None:raise AssertionError('Loopback server exited; '+(root/'server.log').read_text()[-4000:])
            try:
                response=client.get('/api/health')
                if response.status_code==200:break
            except httpx.TransportError:pass
            time.sleep(.1)
        token=check(client.post('/api/auth/login',json={'username':'admin','password':'admin123'}))['access_token']
        client.headers.update({'Authorization':'Bearer '+token})
        project=check(client.post('/api/projects',json={'name':'T25真实流式2GiB隔离验收','start_date':'2026-01-01','end_date':'2026-12-31'}))
        pid=project['id'];documents=check(client.get(f'/api/projects/{pid}/documents'))['documents'];did=documents[0]['id']
        intent={'client_uuid':'real-two-gib-proof-20261027','filename':'original-2GiB.bin','size':args.size,'sha256':sha,'document_ids':[did]}
        session=check(client.post(f'/api/projects/{pid}/uploads',json=intent));sid=session['id'];base=f'/api/projects/{pid}/uploads/{sid}'
        baseline=rss[-1] if rss else 0;chunk_size=session['chunk_size'];sent=0
        def put(index,part):
            return client.put(base+f'/chunks/{index}',content=part,headers={'Content-Type':'application/octet-stream','X-Chunk-SHA256':hashlib.sha256(part).hexdigest()})
        with source.open('rb') as handle:
            for index in range(session['total_chunks']):
                part=handle.read(chunk_size)
                if index==3:
                    client.close() # Lose the original TCP client, preserving only the intent and server receipts.
                    client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token},timeout=300)
                    resumed=check(client.post(f'/api/projects/{pid}/uploads',json=intent))
                    assert resumed['id']==sid and [item['index'] for item in resumed['received']]==[0,1,2]
                check(put(index,part));sent+=len(part)
                if index==0:check(put(index,part))
                if index%32==0:print(json.dumps({'uploaded_bytes':sent,'total':args.size}),flush=True)
        finished=check(client.post(base+'/finish'));repeated=check(client.post(base+'/finish'))
        assert repeated['file']['id']==finished['file']['id']
        actual=hashlib.sha256();downloaded=0
        with client.stream('GET','/api'+finished['file']['download_url']) as response:
            assert response.status_code==200
            for part in response.iter_bytes(1024**2):actual.update(part);downloaded+=len(part)
        assert downloaded==args.size and actual.hexdigest()==sha
        wrong=b'wrong-complete-hash';bad={**intent,'client_uuid':'wrong-whole-hash-proof-001','size':len(wrong),'sha256':'0'*64}
        bad_session=check(client.post(f'/api/projects/{pid}/uploads',json=bad));badbase=f'/api/projects/{pid}/uploads/{bad_session["id"]}'
        check(client.put(badbase+'/chunks/0',content=wrong,headers={'Content-Type':'application/octet-stream','X-Chunk-SHA256':hashlib.sha256(wrong).hexdigest()}))
        check(client.post(badbase+'/finish'),409)
        with psycopg2.connect(url) as db:
            with db.cursor() as cur:
                cur.execute('SELECT file_size,sha256 FROM attachments WHERE project_id=%s',(pid,));rows=cur.fetchall()
                assert rows==[(args.size,sha)]
                cur.execute('SELECT count(*) FROM document_versions WHERE project_document_id=%s',(did,));assert cur.fetchone()[0]==1
        measurement={'size_bytes':args.size,'sha256':sha,'download_sha256':actual.hexdigest(),'interrupted_after_chunks':3,
            'duplicate_chunk_idempotent':True,'duplicate_finish_idempotent':True,'wrong_complete_hash_status':409,
            'attachment_count':1,'version_count':1,'server_baseline_rss_bytes':baseline,'server_peak_rss_bytes':max(rss or [0]),
            'client_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            'elapsed_seconds':round(time.monotonic()-began,2),'data_dir':str(data),'database_name':args.database_url.rsplit('/',1)[-1],
            'source':str(source),'transport':'real uvicorn loopback HTTP, 8-MiB bounded chunks, 1-MiB streaming download'}
        assert measurement['server_peak_rss_bytes']-baseline<512*1024**2,measurement
        Path(args.output).write_text(json.dumps(measurement,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(measurement,ensure_ascii=False),flush=True)
    finally:
        stop.set();server.terminate()
        try:server.wait(timeout=15)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        log.close()


if __name__=='__main__':main()
