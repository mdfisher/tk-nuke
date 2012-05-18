"""
Copyright (c) 2012 Shotgun Software, Inc
----------------------------------------------------

A Nuke engine for Tank.

"""

import tank
import platform
import nuke
import os
import pickle

class TankProgressWrapper(object):
    """
    A progressbar wrapper for nuke.
    Does not currently handle the cancel button.
    It is nice to wrap the nuke object like this because otherwise 
    it can be tricky to delete later.
    """
    def __init__(self, title, ui_enabled):
        self.__ui = ui_enabled
        self.__title = title
        if self.__ui:
            self.__p = nuke.ProgressTask(title)
    
    def set_progress(self, percent):
        if self.__ui:
            self.__p.setProgress(percent)
        else:
            print("TANK_PROGRESS Task:%s Progress:%d%%" % (self.__title, percent))
    
    def close(self):
        if self.__ui:
            self.__p = None



class NukeEngine(tank.system.Engine):
    
    
    ##########################################################################################
    # init
    
    def init_engine(self):
        
        import sg_nuke
        
        self.log_debug("%s: Initializing..." % self)
        
        # now check that there is a location on disk which corresponds to the context
        # for the maya engine (because it for example sets the maya project)
        if len(self.context.entity_locations) == 0:
            # Try to create path for the context.
            tank.system.schema.create_filesystem_structure(self.shotgun,
                                                           self.context.project_root,
                                                           self.context.entity["type"],
                                                           self.context.entity["id"])
            if len(self.context.entity_locations) == 0:
                raise tank.TankError("No folders on disk are associated with the current context. The Nuke "
                                "engine requires a context which exists on disk in order to run "
                                "correctly.")
        
        # make sure we are not running that bloody nuke PLE!
        if nuke.env.get("ple") == True:
            self.log_error("The Nuke Engine does not work with the Nuke PLE!")
            return
        
        # keep track of if a UI exists
        self._ui_enabled = nuke.env.get("gui")
        
        # create queue
        self._queue = []
                    
        # now prepare tank so that it will be picked up by any new processes
        # created by file->new or file->open.
            
        # Store data needed for bootstrapping Tank in env vars. Used in startup/menu.py
        os.environ["TANK_NUKE_ENGINE_INIT_NAME"] = self.name
        os.environ["TANK_NUKE_ENGINE_INIT_CONTEXT"] = pickle.dumps(self.context)
        
        
        # add our startup path to the nuke init path
        startup_path = os.path.abspath(os.path.join( os.path.dirname(__file__), "startup"))
        tank.util.append_path_to_env_var("NUKE_PATH", startup_path)        
    
        # we also need to pass the path to the python folder down to the init script
        # because nuke python does not have a __file__ attribute for that file
        local_python_path = os.path.abspath(os.path.join( os.path.dirname(__file__), "python"))
        os.environ["TANK_NUKE_ENGINE_MOD_PATH"] = local_python_path
    
        # render the menu!
        if self._ui_enabled:
            self._create_menu()
            self.__setup_favourite_dirs()
        
        # make sure callbacks tracking the context switching are active
        sg_nuke.tank_ensure_callbacks_registered()
        
        # iterate over all apps, if there is a gizmo folder, add it to nuke path
        apps_root = os.path.abspath(os.path.join( os.path.dirname(__file__), "apps"))
        for app_name in self.apps:
            # add gizmo to nuke path
            app_gizmo_folder = os.path.join(apps_root, app_name, "gizmos")
            if os.path.exists(app_gizmo_folder):
                self.log_debug("Adding %s to nuke node path" % app_gizmo_folder)
                nuke.pluginAddPath(app_gizmo_folder)
                # and also add it to the plugin path - this is so that any 
                # new processes spawned from this one will have access too.
                # (for example if you do file->open or file->new)
                tank.util.append_path_to_env_var("NUKE_PATH", app_gizmo_folder)

        
                
    def destroy_engine(self):
        self.log_debug("%s: Destroying..." % self)
        if self._ui_enabled:
            self._menu_handle.clearMenu()
            self._node_menu_handle.clearMenu()

    
    ##########################################################################################
    # logging interfaces
    
    def log_debug(self, msg):
        if self.get_setting("debug_logging", False):
            msg = "Tank Debug: %s" % msg
            nuke.debug(msg)


    def log_info(self, msg):
        msg = "Tank Info: %s" % msg
        nuke.debug(msg)

        nuke.debug("Tank: %s" % msg)
        
    def log_warning(self, msg):
        msg = "Tank Warning: %s" % msg
        nuke.warning(msg)
    
    def log_error(self, msg):
        msg = "Tank Error: %s" % msg
        nuke.error(msg)
        # and pop up UI
        nuke.message(msg)
    
    ##########################################################################################
    # managing favourite dirs            
    
    def __setup_favourite_dirs(self):
        """
        Sets up nuke shortcut "favourite dirs"
        that are presented in the left hand side of 
        nuke common dialogs (open, save)
        """
        
        supported_entity_types = ["Shot", "Sequence", "Scene", "Asset", "Project"]
        
        # remove all previous favs
        for x in supported_entity_types:
            nuke.removeFavoriteDir("Tank Current %s" % x)
        
        # get a list of project entities to process
        entities = []
        if self.context.entity:
            # current entity
            entities.append(self.context.entity)
        if self.context.project:
            # current proj
            entities.append(self.context.project)
        
        for x in entities:
            sg_et = x["type"]
            if sg_et not in supported_entity_types:
                # don't know how to remove this, so don't add it!
                continue
            paths = tank.get_paths_for_entity(self.context.project_root, x)
            if len(paths) > 0:
                # for now just pick the first path associated with this entity
                # todo: later on present multiple ones? or decide on a single path to choose?
                path = paths[0]
                nuke.addFavoriteDir("Tank Current %s" % sg_et, 
                                    directory=path,  
                                    type=(nuke.IMAGE|nuke.SCRIPT|nuke.FONT|nuke.GEO), 
                                    icon=self._tk2_logo_small, 
                                    tooltip=path)
    
        # now set up a shortcut for the context
        tmpl = self.tank.templates.get(self.get_setting("template_context"))
        fields = self.context.as_template_fields(tmpl)
        path = tmpl.apply_fields(fields)
        nuke.removeFavoriteDir("Tank Current Work")
        nuke.addFavoriteDir("Tank Current Work", 
                            directory=path,
                            type=(nuke.IMAGE|nuke.SCRIPT|nuke.FONT|nuke.GEO), 
                            icon=self._tk2_logo_small, 
                            tooltip=path)
        
        
    
    ##########################################################################################
    # managing the menu            
    
    def __add_doc_command_to_menu(self, mode, parent):
        """
        Adds documentation to menu, helper 
        """        
        # engine
        docs = self.documentation["engine"]
        doc_url = docs[mode]
        if doc_url:
            cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % doc_url.replace("\\", "/")
            parent.addCommand(docs["display_name"], cmd)            
        
        # now apps
        for app_doc in docs["apps"].values():
            doc_url = app_doc[mode]
            if doc_url:
                cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % doc_url.replace("\\", "/")
                parent.addCommand(app_doc["display_name"], cmd)            

        
    def __add_documentation_to_menu(self):
        """
        Adds documentation items to menu based on what docs are available. 
        """
        
        # create Help menu
        self._menu_handle.addSeparator()
        help_menu = self._menu_handle.addMenu("Help")

        # add index  
        main_url = self.documentation["index"]
        if main_url:
            cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % main_url.replace("\\", "/")
            help_menu.addCommand("Complete Tank Documentation", cmd)
            help_menu.addSeparator()

        # engine
        docs = self.documentation["engine"]
        doc_url = docs["user"]
        if doc_url:
            cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % doc_url.replace("\\", "/")
            help_menu.addCommand(docs["display_name"], cmd)            
        
        # now apps
        for app_doc in docs["apps"].values():
            doc_url = app_doc["user"]
            if doc_url:
                cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % doc_url.replace("\\", "/")
                help_menu.addCommand(app_doc["display_name"], cmd)            

        # add developer docs under developer menu
        help_menu.addSeparator()
        
        engine_docs = self.documentation["engine"]
        doc_url = engine_docs.get("developer")
        if doc_url:
            cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % doc_url.replace("\\", "/")
            help_menu.addCommand("Developer Documentation", cmd)

    def __launch_context_in_fs(self):
        
        tmpl = self.tank.templates.get(self.get_setting("template_context"))
        fields = self.context.as_template_fields(tmpl)
        proj_path = tmpl.apply_fields(fields)
        self.log_debug("Launching file system viewer for folder %s" % proj_path)        
        
        # get the setting        
        system = platform.system()
        
        # run the app
        if system == "Linux":
            cmd = 'xdg-open "%s"' % proj_path
        elif system == "Darwin":
            cmd = 'open "%s"' % proj_path
        elif system == "Windows":
            cmd = 'cmd.exe /C start "Folder" "%s"' % proj_path
        else:
            raise Exception("Platform '%s' is not supported." % system)
        
        self.log_debug("Executing command '%s'" % cmd)
        exit_code = os.system(cmd)
        if exit_code != 0:
            self.log_error("Failed to launch '%s'!" % cmd)





    def __add_context_menu(self):
        """
        Adds a context menu which displays the current context
        """        
        
        ctx = self.context
        
        # try to figure out task/step, however this may not always be present
        task_step = None
        if ctx.step:
            task_step = ctx.step.get("name")
        if ctx.task:
            task_step = ctx.task.get("name")

        if task_step is None:
            # e.g. [Shot ABC_123]
            ctx_name = "[%s %s]" % (ctx.entity["type"], ctx.entity["name"])
        else:
            # e.g. [Lighting, Shot ABC_123]
            ctx_name = "[%s, %s %s]" % (task_step, ctx.entity["type"], ctx.entity["name"])
        
        # create the menu object        
        self._ctx_menu_handle = self._menu_handle.addMenu(ctx_name)
                
        # link to shotgun
        sg_url = "%s/detail/%s/%d" % (self.shotgun.base_url, ctx.entity["type"], ctx.entity["id"])
        cmd = "import nukescripts.openurl; nukescripts.openurl.start('%s')" % sg_url
        self._ctx_menu_handle.addCommand("Show %s in Shotgun" % ctx.entity["type"], cmd)
        
        # link to fs
        self._ctx_menu_handle.addCommand("Show in File System", self.__launch_context_in_fs)        
        
        # and finally a separator
        self._menu_handle.addSeparator()
    
    
    def _add_command_to_menu(self, cmd):
        """
        Adds an app command to the menu
        """
        properties = cmd["properties"]
        
        if properties.get("type") == "node":
            # this should go on the custom node menu!
            
            # get icon if specified - default to tank icon if not specified
            icon = properties.get("icon", self._tk2_logo)
            self._node_menu_handle.addCommand(cmd["name"], cmd["callback"], icon=icon)

        elif properties.get("type") == "context_menu":
            self._ctx_menu_handle.addCommand(cmd["name"], cmd["callback"] )
        else:
            # std shotgun menu
            self._menu_handle.addCommand(cmd["name"], cmd["callback"] ) 
            
        
    
    def _create_menu(self):
        """
        Render the entire Tank menu.
        """
        # create main menu
        nuke_menu = nuke.menu("Nuke")
        self._menu_handle = nuke_menu.addMenu("Tank") 
        
        # slight hack here but first ensure that the menu is empty
        self._menu_handle.clearMenu()

        # create tank side menu
        this_folder = os.path.dirname(__file__)
        self._tk2_logo = os.path.abspath(os.path.join(this_folder, "resources", "box_22.png"))
        self._tk2_logo_small = os.path.abspath(os.path.join(this_folder, "resources", "box_16.png"))
        self._node_menu_handle = nuke.menu("Nodes").addMenu("Tank", icon=self._tk2_logo)
    
        self.__add_context_menu()
        
        for cmd in self._get_commands():
            self._add_command_to_menu(cmd)
            
        self.__add_documentation_to_menu()
            
    ##########################################################################################
    # queue

    def add_to_queue(self, name, method, args):
        """
        Nuke implementation of the engine synchronous queue. Adds an item to the queue.
        """
        qi = {}
        qi["name"] = name
        qi["method"] = method
        qi["args"] = args
        self._queue.append(qi)
    
    def report_progress(self, percent):
        """
        Callback function part of the engine queue. This is being passed into the methods
        that are executing in the queue so that they can report progress back if they like
        """
        self._current_queue_item["progress"].set_progress(percent)
    
    def execute_queue(self):
        """
        Executes all items in the queue, one by one, in a controlled fashion
        """
        # create progress items for all queue items
        for x in self._queue:
            x["progress"] = TankProgressWrapper(x["name"], self._ui_enabled)

        # execute one after the other syncronously
        while len(self._queue) > 0:
            
            # take one item off
            self._current_queue_item = self._queue[0]
            self._queue = self._queue[1:]
            
            # process it
            try:
                kwargs = self._current_queue_item["args"]
                # force add a progress_callback arg - this is by convention
                kwargs["progress_callback"] = self.report_progress
                # execute
                self._current_queue_item["method"](**kwargs)
            except:
                # error and continue
                # todo: may want to abort here - or clear the queue? not sure.
                self.log_exception("Error while processing callback %s" % self._current_queue_item)
            finally:
                self._current_queue_item["progress"].close()
        

            
            
            