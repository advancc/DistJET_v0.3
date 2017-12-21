import os,sys
import ConfigParser
if not os.environ.has_key('DistJETPATH'):
    print "There is no environment path"
    exit()
sys.path.append(os.environ['DistJETPATH'])
import python.Util.Config as Config
config_path = os.environ['DistJETPATH']+'/config.ini'
if not os.path.exists(config_path):
    print "Can not find running job, exit"
    exit()

cf = ConfigParser.ConfigParser()
cf.read(config_path)
run_path = cf.get('GlobalCfg','Rundir')
task_path = cf.get('GlobalCfg','Rundir')+'/task_log'
print task_path
if not os.path.exists(task_path):
    print "Wrong task directory, exit"
    exit()
succ = 0
running = 0
err = 0
for file_name in os.listdir(task_path):
    if file_name.endswith('.tmp'):
        running+=1
    elif file_name.endswith('.err'):
        err+=1
    else:
        succ+=1
if succ==0 and running==0 and err==0:
    print "System is initializing, no task generate"
    exit()
#parse AppMgr.log
total = 0
if os.path.exists(run_path+'/DistJET_log/DistJET.AppMgr.log'):
    appmgr_log = open(run_path+'/DistJET_log/DistJET.AppMgr.log')
    for line in appmgr_log.readlines():
        if '[AppMgr]: Create' in line:
            line = line.split()
            for s in line:
                if s.isdigit():
                    total = int(s)
                    break
            break
    appmgr_log.close()

print "-----task status-----"
print "running: %d tasks"%running
print "success: %d tasks"%succ
print "error: %d tasks"%err
print "total: %d tasks"%total
