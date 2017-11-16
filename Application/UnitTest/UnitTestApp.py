from python.IApplication.JunoApp import JunoApp
from python.Task import TaskStatus,Task
import getpass
import os
import subprocess
import types

class UnitTestApp(JunoApp):
    def __init__(self,rootdir, name, config_path=None):
        super(UnitTestApp,self).__init__(rootdir,name,config_path)
        self.task_reslist={}
        self.app_boot.append("$JUNOTESTROOT/python/JunoTest/junotest UnitTest")
        self.setStatus('boot') 

    def split(self):
        self.data[0]=[]
        self.data[0].append('Tutorial')
        self.data[0].append('Cf252')
        self.setStatus('data')
        task_list = []
        for data in self.data[0]:
            task = Task()
            task.boot = self.app_boot
            task.data[0] = data
            task.res_dir = self.res_dir
            task_list.append(task)

        return task_list

    def split_bak(self):
        rc = subprocess.Popen(["python",os.environ['JUNOTESTROOT']+"/python/JunoTest/junotest","UnitTest","list"],stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        unitcase, err = rc.communicate()
        if err:
            self.log.error('[APP_%d] @split() err = %s'%(self.id,str(err)))
        case = unitcase.split('\n')
        startline = 0
        for line in case:
            startline+=1
            if 'unittest cases' in line:
                break
        for c in case[startline:]:
            if c!= '' :
                if not self.data.has_key(0):
                    self.data[0] = []
                self.data[0].append(c)
        self.log.info('[App_%d] split data = %s'%(self.id, self.data))
        self.setStatus('data')
        return self.data


    def merge(self, tasklist):
        for task in tasklist.values():
            with open(self.res_dir+'/summary.log','a+') as resfile:
                data = ''
                if type(task.data) == types.DictType:
                    for d in task.data.values():
                        data+=d+' '
                else:
                    data = task.data
                if task.status == TaskStatus.COMPLETED:
                    resfile.writelines(str(task.tid)+' '+data+'  SUCCESS\n')
                    #resfile.writelines(task.toString())
                    resfile.flush()
                else:
                    resfile.writelines(str(task.tid)+' '+data+'  FAIL\n')
                    resfile.flush()


    def analyze_log(self,logname):
        logpath = self.res_dir+'/app_%s_task_%s'%(self.id,logname)
        if not os.path.exists(logpath):
            self.log.error("[App_%d] Cannot find log file %s"%(self.id,logpath))
            return False
        with open(logpath,'a+') as logFile:
            self.log.debug('[App_%d] Parse log file %s'%(self.id,logpath))
            for line in logFile:
                if line.find('ERROR') != -1:
                    self.log.info('Find ERROR in log file, task fail')
                    return False
                else:
                    return True

    def uninstall(self):
        comm = 'ps -ef|grep %s|grep "python /afs/ihep.ac.cn/soft/juno/JUNO-ALL-SLC6"|grep -v grep| awk %s|xargs kill'%(getpass.getuser(),"'{print $2}'")
        self.log.info("[UnitTest] Uninstall command = %s"%comm)
        #return ['ps -ef|grep %s|grep -v grep'%getpass.getuser(),comm,'ps -ef|grep %s|grep -v grep'%getpass.getuser()]
        return []
