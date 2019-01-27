# -*- coding: utf-8 -*-
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

from flask import g
from flask_appbuilder.security.sqla import models as sqla_models
from flask_appbuilder.security.sqla.manager import SecurityManager
from sqlalchemy import or_

from airflow import models
from airflow.www_rbac.app import appbuilder
from airflow.utils.db import provide_session
from airflow.utils.log.logging_mixin import LoggingMixin

###########################################################################
#                               VIEW MENUS
###########################################################################
VIEWER_VMS = {
    'Airflow',
    'DagModelView',
    'Browse',
    'DAG Runs',
    'DagRunModelView',
    'Task Instances',
    'TaskInstanceModelView',
    'SLA Misses',
    'SlaMissModelView',
    'Jobs',
    'JobModelView',
    'Logs',
    'LogModelView',
    'Docs',
    'Documentation',
    'Github',
    'About',
    'Version',
    'VersionView',
}

USER_VMS = VIEWER_VMS

OP_VMS = {
    'Admin',
    'Configurations',
    'ConfigurationView',
    'Connections',
    'ConnectionModelView',
    'Pools',
    'PoolModelView',
    'Variables',
    'VariableModelView',
    'XComs',
    'XComModelView',
}

###########################################################################
#                               PERMISSIONS
###########################################################################

VIEWER_PERMS = {
    'menu_access',
    'can_index',
    'can_list',
    'can_show',
    'can_chart',
    'can_dag_stats',
    'can_dag_details',
    'can_task_stats',
    'can_code',
    'can_log',
    'can_get_logs_with_metadata',
    'can_tries',
    'can_graph',
    'can_tree',
    'can_task',
    'can_task_instances',
    'can_xcom',
    'can_gantt',
    'can_landing_times',
    'can_duration',
    'can_blocked',
    'can_rendered',
    'can_pickle_info',
    'can_version',
}

USER_PERMS = {
    'can_dagrun_clear',
    'can_run',
    'can_trigger',
    'can_add',
    'can_edit',
    'can_delete',
    'can_paused',
    'can_refresh',
    'can_success',
    'muldelete',
    'set_failed',
    'set_running',
    'set_success',
    'clear',
    'can_clear',
}

OP_PERMS = {
    'can_conf',
    'can_varimport',
}

# global view-menu for dag-level access
DAG_VMS = {
    'all_dags'
}

DAG_PERMS = {
    'can_dag_read',
    'can_dag_edit',
}

###########################################################################
#                     DEFAULT ROLE CONFIGURATIONS
###########################################################################

ROLE_CONFIGS = [
    {
        'role': 'Viewer',
        'perms': VIEWER_PERMS,
        'vms': VIEWER_VMS | DAG_VMS,
    },
    {
        'role': 'User',
        'perms': VIEWER_PERMS | USER_PERMS | DAG_PERMS,
        'vms': VIEWER_VMS | DAG_VMS | USER_VMS,
    },
    {
        'role': 'Op',
        'perms': VIEWER_PERMS | USER_PERMS | OP_PERMS | DAG_PERMS,
        'vms': VIEWER_VMS | DAG_VMS | USER_VMS | OP_VMS,
    },
]

EXISTING_ROLES = {
    'Admin',
    'Viewer',
    'User',
    'Op',
    'Public',
}


class AirflowSecurityManager(SecurityManager, LoggingMixin):

    def init_role(self, role_name, role_vms, role_perms):
        """
        Initialize the role with the permissions and related view-menus.

        :param role_name:
        :param role_vms:
        :param role_perms:
        :return:
        """
        pvms = self.get_session.query(sqla_models.PermissionView).all()
        pvms = [p for p in pvms if p.permission and p.view_menu]

        role = self.find_role(role_name)
        if not role:
            role = self.add_role(role_name)

        if len(role.permissions) == 0:
            self.log.info('Initializing permissions for role:%s in the database.', role_name)
            role_pvms = set()
            for pvm in pvms:
                if pvm.view_menu.name in role_vms and pvm.permission.name in role_perms:
                    role_pvms.add(pvm)
            role.permissions = list(role_pvms)
            self.get_session.merge(role)
            self.get_session.commit()
        else:
            self.log.info('Existing permissions for the role:%s within the database will persist.', role_name)

    def get_user_roles(self, user=None):
        """
        Get all the roles associated with the user.

        :param user: the ab_user in FAB model.
        :return: a list of roles associated with the user.
        """
        if user is None:
            user = g.user
        if user.is_anonymous:
            public_role = appbuilder.config.get('AUTH_ROLE_PUBLIC')
            return [appbuilder.security_manager.find_role(public_role)] \
                if public_role else []
        return user.roles

    def get_all_permissions_views(self):
        """
        Returns a set of tuples with the perm name and view menu name
        """
        perms_views = set()
        for role in self.get_user_roles():
            perms_views.update({(perm_view.permission.name, perm_view.view_menu.name)
                                for perm_view in role.permissions})
        return perms_views

    def get_accessible_dag_ids(self, username=None):
        """
        Return a set of dags that user has access to(either read or write).

        :param username: Name of the user.
        :return: A set of dag ids that the user could access.
        """
        if not username:
            username = g.user

        if username.is_anonymous or 'Public' in username.roles:
            # return an empty set if the role is public
            return set()

        roles = {role.name for role in username.roles}
        if {'Admin', 'Viewer', 'User', 'Op'} & roles:
            return DAG_VMS

        user_perms_views = self.get_all_permissions_views()
        # return a set of all dags that the user could access
        return set([view for perm, view in user_perms_views if perm in DAG_PERMS])

    def has_access(self, permission, view_name, user=None):
        """
        Verify whether a given user could perform certain permission
        (e.g can_read, can_write) on the given dag_id.

        :param str permission: permission on dag_id(e.g can_read, can_edit).
        :param str view_name: name of view-menu(e.g dag id is a view-menu as well).
        :param str user: user name
        :return: a bool whether user could perform certain permission on the dag_id.
        """
        if not user:
            user = g.user
        if user.is_anonymous:
            return self.is_item_public(permission, view_name)
        return self._has_view_access(user, permission, view_name)

    def _get_and_cache_perms(self):
        """
        Cache permissions-views
        """
        self.perms = self.get_all_permissions_views()

    def _has_role(self, role_name_or_list):
        """
        Whether the user has this role name
        """
        if not isinstance(role_name_or_list, list):
            role_name_or_list = [role_name_or_list]
        return any(
            [r.name in role_name_or_list for r in self.get_user_roles()])

    def _has_perm(self, permission_name, view_menu_name):
        """
        Whether the user has this perm
        """
        if hasattr(self, 'perms'):
            if (permission_name, view_menu_name) in self.perms:
                return True
        # rebuild the permissions set
        self._get_and_cache_perms()
        return (permission_name, view_menu_name) in self.perms

    def has_all_dags_access(self):
        """
        Has all the dag access in any of the 3 cases:
        1. Role needs to be in (Admin, Viewer, User, Op).
        2. Has can_dag_read permission on all_dags view.
        3. Has can_dag_edit permission on all_dags view.
        """
        return (
            self._has_role(['Admin', 'Viewer', 'Op', 'User']) or
            self._has_perm('can_dag_read', 'all_dags') or
            self._has_perm('can_dag_edit', 'all_dags'))

    def clean_perms(self):
        """
        FAB leaves faulty permissions that need to be cleaned up
        """
        self.log.info('Cleaning faulty perms')
        sesh = self.get_session
        pvms = (
            sesh.query(sqla_models.PermissionView)
            .filter(or_(
                sqla_models.PermissionView.permission == None,  # NOQA
                sqla_models.PermissionView.view_menu == None,  # NOQA
            ))
        )
        deleted_count = pvms.delete()
        sesh.commit()
        if deleted_count:
            self.log.info('Deleted {} faulty permissions'.format(deleted_count))

    def _merge_perm(self, permission_name, view_menu_name):
        """
        Add the new permission , view_menu to ab_permission_view_role if not exists.
        It will add the related entry to ab_permission
        and ab_view_menu two meta tables as well.

        :param str permission_name: Name of the permission.
        :param str view_menu_name: Name of the view-menu

        :return:
        """
        permission = self.find_permission(permission_name)
        view_menu = self.find_view_menu(view_menu_name)
        pv = None
        if permission and view_menu:
            pv = self.get_session.query(self.permissionview_model).filter_by(
                permission=permission, view_menu=view_menu).first()
        if not pv and permission_name and view_menu_name:
            self.add_permission_view_menu(permission_name, view_menu_name)

    @provide_session
    def create_custom_dag_permission_view(self, session=None):
        """
        Workflow:
        1. Fetch all the existing (permissions, view-menu) from Airflow DB.
        2. Fetch all the existing dag models that are either active or paused. Exclude the subdags.
        3. Create both read and write permission view-menus relation for every dags from step 2
        4. Find out all the dag specific roles(excluded pubic, admin, viewer, op, user)
        5. Get all the permission-vm owned by the user role.
        6. Grant all the user role's permission-vm except the all-dag view-menus to the dag roles.
        7. Commit the updated permission-vm-role into db

        :return: None.
        """
        # todo(Tao): should we put this function here or in scheduler loop?
        self.log.info('Fetching a set of all permission, view_menu from FAB meta-table')

        def merge_pv(perm, view_menu):
            """Create permission view menu only if it doesn't exist"""
            if view_menu and perm and (view_menu, perm) not in all_pvs:
                self._merge_perm(perm, view_menu)

        all_pvs = set()
        for pv in self.get_session.query(self.permissionview_model).all():
            if pv.permission and pv.view_menu:
                all_pvs.add((pv.permission.name, pv.view_menu.name))

        # create perm for global logical dag
        for dag in DAG_VMS:
            for perm in DAG_PERMS:
                merge_pv(perm, dag)

        # Get all the active / paused dags and insert them into a set
        all_dags_models = session.query(models.DagModel)\
            .filter(or_(models.DagModel.is_active, models.DagModel.is_paused))\
            .filter(~models.DagModel.is_subdag).all()

        # create can_dag_edit and can_dag_read permissions for every dag(vm)
        for dag in all_dags_models:
            for perm in DAG_PERMS:
                merge_pv(perm, dag.dag_id)

        # for all the dag-level role, add the permission of viewer
        # with the dag view to ab_permission_view
        all_roles = self.get_all_roles()
        user_role = self.find_role('User')

        dag_role = [role for role in all_roles if role.name not in EXISTING_ROLES]
        update_perm_views = []

        # need to remove all_dag vm from all the existing view-menus
        dag_vm = self.find_view_menu('all_dags')
        ab_perm_view_role = sqla_models.assoc_permissionview_role
        perm_view = self.permissionview_model
        view_menu = self.viewmenu_model

        all_perm_view_by_user = session.query(ab_perm_view_role)\
            .join(perm_view, perm_view.id == ab_perm_view_role
                  .columns.permission_view_id)\
            .filter(ab_perm_view_role.columns.role_id == user_role.id)\
            .join(view_menu)\
            .filter(perm_view.view_menu_id != dag_vm.id)
        all_perm_views = set([role.permission_view_id for role in all_perm_view_by_user])

        for role in dag_role:
            # Get all the perm-view of the role
            existing_perm_view_by_user = self.get_session.query(ab_perm_view_role)\
                .filter(ab_perm_view_role.columns.role_id == role.id)

            existing_perms_views = set([pv.permission_view_id
                                        for pv in existing_perm_view_by_user])
            missing_perm_views = all_perm_views - existing_perms_views

            for perm_view_id in missing_perm_views:
                update_perm_views.append({'permission_view_id': perm_view_id,
                                          'role_id': role.id})

        self.get_session.execute(ab_perm_view_role.insert(), update_perm_views)
        self.get_session.commit()

    def update_admin_perm_view(self):
        """
        Admin should have all the permission-views.
        Add the missing ones to the table for admin.

        :return: None.
        """
        pvms = self.get_session.query(sqla_models.PermissionView).all()
        pvms = [p for p in pvms if p.permission and p.view_menu]

        admin = self.find_role('Admin')
        admin.permissions = list(set(admin.permissions) | set(pvms))

        self.get_session.commit()

    def sync_roles(self):
        """
        1. Init the default role(Admin, Viewer, User, Op, public)
           with related permissions.
        2. Init the custom role(dag-user) with related permissions.

        :return: None.
        """
        self.log.info('Start syncing user roles.')
        # Create global all-dag VM
        self.create_perm_vm_for_all_dag()

        # Create default user role.
        for config in ROLE_CONFIGS:
            role = config['role']
            vms = config['vms']
            perms = config['perms']
            self.init_role(role, vms, perms)
        self.create_custom_dag_permission_view()

        # init existing roles, the rest role could be created through UI.
        self.update_admin_perm_view()
        self.clean_perms()

    def sync_perm_for_dag(self, dag_id):
        """
        Sync permissions for given dag id. The dag id surely exists in our dag bag
        as only / refresh button will call this function

        :param dag_id:
        :return:
        """
        for dag_perm in DAG_PERMS:
            perm_on_dag = self.find_permission_view_menu(dag_perm, dag_id)
            if perm_on_dag is None:
                self.add_permission_view_menu(dag_perm, dag_id)

    def create_perm_vm_for_all_dag(self):
        """
        Create perm-vm if not exist and insert into FAB security model for all-dags.
        """
        # create perm for global logical dag
        for dag_vm in DAG_VMS:
            for perm in DAG_PERMS:
                self._merge_perm(permission_name=perm,
                                 view_menu_name=dag_vm)
