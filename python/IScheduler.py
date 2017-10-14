import Queue

import WorkerRegistry
import Task
import IAppManager

from Util import logger
from Util.Config import Config

scheduler_log = logger.getLogger('AppMgr')



class IScheduler:
    def __init__(self, master, appmgr, worker_registry=None):
        self.master = master
        self.appid = None
        self.worker_registry = worker_registry
        self.appmgr = appmgr
        self.task_todo_queue = Queue.Queue() # task queue, store task obj
        scheduler_log.info('[Scheduler] Load tasks created by AppMgr')
        self.task_list = self.appmgr.get_app_task_list()
        for tid, task in self.task_list.items():
            if isinstance(task, Task.ChainTask) and task.father_len == 0:
                self.task_todo_queue.put(tid)
            else:
                self.task_todo_queue.put(tid)
        scheduler_log.info('[Scheduler] Load %d tasks'%self.task_todo_queue.qsize())
        self.scheduled_task_list = {}       # wid: tid_list
        self.completed_queue = Queue.Queue()
        self.runflag = self.task_todo_queue.qsize() > 0

    def initialize(self):
        """
        Initialize the TaskScheduler passing the job input parameters as specified by the user when starting the run.
        :return:
        """
        pass

    def run(self):
        """
        :return:
        """
        pass

    def finalize(self):
        """
        The operation when Scheduler exit
        :return:
        """
        pass

    def assignTask(self, w_entry):
        """
        The master call this method when a Worker ask for tasks
        :param w_entry:
        :return: a list of assigned task obj
        """
        raise NotImplementedError

    def setWorkerRegistry(self, worker_registry):
        """
        :param worker_registry:
        :return:
        """
        self.worker_registry = worker_registry

    def has_more_work(self):
        """
        Return ture if current app has more work( when the number of works of app is larger than sum of workers' capacities)
        :return: bool
        """
        #if not self.task_todo_queue.empty():
            #scheduler_log.debug('task_todo_quue has task num = %d'%self.task_todo_queue.qsize())
        return not self.task_todo_queue.empty()

    def has_scheduled_work(self,wid=None):
        if wid:
            return len(self.scheduled_task_list[wid])!=0
        else:
            flag = False
            for k in self.scheduled_task_list.keys():
                if len(self.scheduled_task_list[k]) != 0:
                    #scheduler_log.debug('worker %d has task %s'%(k,self.scheduled_task_list[k]))
                    flag = True
                    break
        return flag

    def task_failed(self, wid, tid, time_start, time_finish, error):
        """
        called when tasks completed with failure
        :param wid: worker id
        :param tid: task id
        :param time_start:  the start time of the task, used for recoding
        :param time_finish: the end time of the task, used for recoding
        :param error: error code of the task
        :return:
        """
        raise NotImplementedError

    def task_completed(self, wid, task):
        """
        this method is called when task completed ok.
        :param wid:
        :param tid:
        :param time_start:
        :param time_finish:
        :return:
        """
        raise NotImplementedError

    def get_task(self,tid):
        return self.task_list[tid]

    def worker_finalized(self, wid):
        """
        worker finalize a app, and can start another app
        :param wid:
        :return:
        """
        raise  NotImplementedError

    def setup_worker(self):
        """
        returns the setup command of the app
        :return:
        """
        return self.appmgr.setup_app()

    def uninstall_worker(self):
        """
        return the unsetup command of app
        :return:
        """
        return self.appmgr.uninstall_app()


# -------------------------discard-------------------------------
    def init_worker(self):
        app = self.appmgr.get_current_app()
        task_dict = {}
        task_dict['boot'] = app.app_init_boot
        task_dict['args'] = {}
        task_dict['data'] = {}
        task_dict = dict(task_dict, **app.app_init_extra)
        task_dict['resdir'] = app.res_dir
        return task_dict

    def fin_worker(self):
        app = self.appmgr.get_current_app()
        task_dict = {}
        task_dict['boot'] = app.app_fin_boot
        task_dict['resdir'] = app.res_dir
        task_dict['data'] = {}
        task_dict['args'] = {}
        task_dict = dict(task_dict,**app.app_fin_extra)
        return task_dict

    def worker_initialized(self, wid):
        """
        called by Master when a worker agent successfully initialized the worker, (maybe check the init_output)
        when the method returns, the worker can be marked as ready
        :param wid:
        :return:
        """
        raise NotImplementedError

    def worker_added(self, wid):
        """
        This method is called by RunMaster when the new worker agent is added. Application specific initialization data
        may be assigned to w_entry.init_input at this point.
        :param wid:
        :return:
        """
        raise NotImplementedError

    def worker_removed(self, wid, time_point):
        """
        This method is called when the worker has been removed (either lost or terminated due to some reason).
        :param wid:
        :return:
        """
        raise
# -------------------------discard-------------------------------

class SampleTaskScheduler(IScheduler):

    def assignTask(self, wid):
        room = self.worker_registry.get_entry(wid).capacity()
        task_list = []
        if not self.scheduled_task_list.has_key(wid):
            self.scheduled_task_list[wid] = []
        if self.task_todo_queue.empty():
            # pull idle task back from worker and assign to other worker
            # try pull back task
            for wid, worker_task_list in self.scheduled_task_list.items():
                while len(worker_task_list) > self.worker_registry.get_capacity(wid) :
                    flag, tmptask = self.master.try_pullback(wid,worker_task_list[-1])
                    if flag:
                        worker_task_list.pop()
                        break
                task = self.task_list[tmptask.tid]
                task.update(tmptask)
                task.assign(wid)
                task_list.append(task)
                self.scheduled_task_list[wid].append(task.tid)

        else:
            # assign 1 task once
            if not self.task_todo_queue.empty():
                tid = self.task_todo_queue.get()
                self.get_task(tid).assign(wid)
                task_list.append(self.get_task(tid))
                self.scheduled_task_list[wid].append(tid)
            # assign tasks depends on the capacity of task
            #while room >= 1 and not self.task_todo_queue.empty():
            #    tid = self.task_todo_queue.get()
            #    self.get_task(tid).assign(wid)
            #    task_list.append(tid)
            #    room-=1
            #    self.scheduled_task_list[wid].append(tid)
        if task_list:
            scheduler_log.debug('[Scheduler] Assign %s to worker %s' % (self.scheduled_task_list[wid][-room:], wid))
        return task_list


    def task_completed(self, wid, task):
        wid = int(wid)
        tid = task.tid
        # delete from scheduled task list
        if tid in self.scheduled_task_list[wid]:
            self.scheduled_task_list[wid].remove(tid)
        scheduler_log.info('[Scheduler] Task %s complete' % tid)
        scheduler_log.debug('[Scheduler] Task %s complete, remove form scheduled_task_list, now = %s' % (tid, self.scheduled_task_list))

        # update chain task
        if isinstance(task,Task.ChainTask):
            for child_id in task.get_child_list():
                child = self.task_list(child_id)
                child.remove_father(task.tid)
                if child.father_len == 0:
                    self.task_todo_queue.put(child)
                    scheduler_log.debug('[Scheduler] ChainTask %s add to todo list'%child.tid)

    def worker_initialized(self, wid):
        entry = self.worker_registry.get_entry(wid)
        try:
            entry.alive_lock.acquire()
            entry.status = WorkerRegistry.WorkerStatus.INITILAZED
        finally:
            entry.alive_lock.release()

    def worker_removed(self, wid, time_point):
        """
        when worker is force removed, add scheduled tasks back to queue
        :param wid:
        :param time_point:
        :return:
        """
        tl = []
        for tid in self.scheduled_task_list[wid]:
            tl.append(tid)
            task = self.get_task(tid)
            task.withdraw(time_point)
            self.task_todo_queue.put(task.tid)
            self.scheduled_task_list[wid].remove(tid)

        scheduler_log.info("[Scheduler] Remove worker %s, pull back tasks %s"%(wid,tl))

    def worker_finalized(self, wid):
        if self.worker_registry.isAlive(wid):
            try:
                w = self.worker_registry.get_entry(wid)
                w.lock.acquire()
                w.status = WorkerRegistry.WorkerStatus.FINALIZED
            finally:
                w.lock.release()

