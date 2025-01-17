#!/usr/bin/env python3
#
# Copyright (C) 2017 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Installs VNDK snapshot under prebuilts/vndk/v{version}."""

import argparse
import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

import utils

from check_gpl_license import GPLChecker
from gen_buildfiles import GenBuildFile

ANDROID_BUILD_TOP = utils.get_android_build_top()
PREBUILTS_VNDK_DIR = utils.join_realpath(ANDROID_BUILD_TOP, 'prebuilts/vndk')


def start_branch(build):
    branch_name = 'update-' + (build or 'local')
    logging.info('Creating branch {branch} in {dir}'.format(
        branch=branch_name, dir=os.getcwd()))
    utils.check_call(['repo', 'start', branch_name, '.'])


def remove_old_snapshot(install_dir):
    logging.info('Removing any old files in {}'.format(install_dir))
    for file in glob.glob('{}/*'.format(install_dir)):
        try:
            if os.path.isfile(file):
                os.unlink(file)
            elif os.path.isdir(file):
                shutil.rmtree(file)
        except Exception as error:
            logging.error('Error: {}'.format(error))
            sys.exit(1)


def install_snapshot(branch, build, local_dir, install_dir, temp_artifact_dir):
    """Installs VNDK snapshot build artifacts to prebuilts/vndk/v{version}.

    1) Fetch build artifacts from Android Build server or from local_dir
    2) Unzip build artifacts

    Args:
      branch: string or None, branch name of build artifacts
      build: string or None, build number of build artifacts
      local_dir: string or None, local dir to pull artifacts from
      install_dir: string, directory to install VNDK snapshot
      temp_artifact_dir: string, temp directory to hold build artifacts fetched
        from Android Build server. For 'local' option, is set to None.
    """
    artifact_pattern = 'android-vndk-*.zip'

    if branch and build:
        artifact_dir = temp_artifact_dir
        os.chdir(temp_artifact_dir)
        logging.info('Fetching {pattern} from {branch} (bid: {build})'.format(
            pattern=artifact_pattern, branch=branch, build=build))
        utils.fetch_artifact(branch, build, artifact_pattern)

        manifest_pattern = 'manifest_{}.xml'.format(build)
        logging.info('Fetching {file} from {branch} (bid: {build})'.format(
            file=manifest_pattern, branch=branch, build=build))
        utils.fetch_artifact(branch, build, manifest_pattern,
                             utils.MANIFEST_FILE_NAME)

        os.chdir(install_dir)
    elif local_dir:
        logging.info('Fetching local VNDK snapshot from {}'.format(local_dir))
        artifact_dir = local_dir

    artifacts = glob.glob(os.path.join(artifact_dir, artifact_pattern))
    for artifact in artifacts:
        logging.info('Unzipping VNDK snapshot: {}'.format(artifact))
        utils.check_call(['unzip', '-qn', artifact, '-d', install_dir])

        # rename {install_dir}/{arch}/include/out/soong/.intermediates
        for soong_intermediates_dir in glob.glob(install_dir + '/*/include/' + utils.SOONG_INTERMEDIATES_DIR):
            generated_headers_dir = soong_intermediates_dir.replace(
                utils.SOONG_INTERMEDIATES_DIR,
                utils.GENERATED_HEADERS_DIR
            )
            os.rename(soong_intermediates_dir, generated_headers_dir)

def gather_notice_files(install_dir):
    """Gathers all NOTICE files to a common NOTICE_FILES directory."""

    common_notices_dir = utils.NOTICE_FILES_DIR_PATH
    logging.info('Creating {} directory to gather all NOTICE files...'.format(
        common_notices_dir))
    os.makedirs(common_notices_dir)
    for arch in utils.get_snapshot_archs(install_dir):
        notices_dir_per_arch = os.path.join(arch, utils.NOTICE_FILES_DIR_NAME)
        if os.path.isdir(notices_dir_per_arch):
            for notice_file in glob.glob(
                    '{}/*.txt'.format(notices_dir_per_arch)):
                if not os.path.isfile(
                        os.path.join(common_notices_dir,
                                     os.path.basename(notice_file))):
                    shutil.copy(notice_file, common_notices_dir)
            shutil.rmtree(notices_dir_per_arch)


def post_processe_files_if_needed(vndk_version):
    """Renames vndkcore.libraries.txt and vndksp.libraries.txt
    files to have version suffix.
    Create empty vndkproduct.libraries.txt file if not exist.

    Args:
      vndk_version: int, version of VNDK snapshot
    """
    def add_version_suffix(file_name):
        logging.info('Rename {} to have version suffix'.format(file_name))
        target_files = glob.glob(
            os.path.join(utils.CONFIG_DIR_PATH_PATTERN, file_name))
        for target_file in target_files:
            name, ext = os.path.splitext(target_file)
            os.rename(target_file, name + '.' + str(vndk_version) + ext)
    def create_empty_file_if_not_exist(file_name):
        target_dirs = glob.glob(utils.CONFIG_DIR_PATH_PATTERN)
        for dir in target_dirs:
            path = os.path.join(dir, file_name)
            if os.path.isfile(path):
                continue
            logging.info('Creating empty file: {}'.format(path))
            open(path, 'a').close()

    files_to_add_version_suffix = ('vndkcore.libraries.txt',
                                   'vndkprivate.libraries.txt')
    files_to_create_if_not_exist = ('vndkproduct.libraries.txt',)
    for file_to_rename in files_to_add_version_suffix:
        add_version_suffix(file_to_rename)
    for file_to_create in files_to_create_if_not_exist:
        create_empty_file_if_not_exist(file_to_create)


def update_buildfiles(buildfile_generator):
    logging.info('Generating root Android.bp file...')
    buildfile_generator.generate_root_android_bp()

    logging.info('Generating common/Android.bp file...')
    buildfile_generator.generate_common_android_bp()

    logging.info('Generating Android.bp files...')
    buildfile_generator.generate_android_bp()

def copy_owners(root_dir, install_dir):
    path = os.path.dirname(__file__)
    shutil.copy(os.path.join(root_dir, path, 'OWNERS'), install_dir)

def check_gpl_license(license_checker):
    try:
        license_checker.check_gpl_projects()
    except ValueError as error:
        logging.error('***CANNOT INSTALL VNDK SNAPSHOT***: {}'.format(error))
        raise


def commit(branch, build, version):
    logging.info('Making commit...')
    utils.check_call(['git', 'add', '.'])
    message = textwrap.dedent("""\
        Update VNDK snapshot v{version} to build {build}.

        Taken from branch {branch}.""").format(
        version=version, branch=branch, build=build)
    utils.check_call(['git', 'commit', '-m', message])


def run(vndk_version, branch, build_id, local, use_current_branch, remote,
        verbose):
    ''' Fetch and updtate the VNDK snapshots

    Args:
      vndk_version: int, VNDK snapshot version to install.
      branch: string, Branch to pull build from.
      build: string, Build number to pull.
      local: string, Fetch local VNDK snapshot artifacts from specified local
             directory instead of Android Build server.
      use-current-branch: boolean, Perform the update in the current branch.
                          Do not repo start.
      remote: string, Remote name to fetch and check if the revision of VNDK
              snapshot is included in the source to conform GPL license.
      verbose: int, Increase log output verbosity.
    '''
    local_path = None
    if local:
        local_path = os.path.abspath(os.path.expanduser(local))

    if local_path:
        if build_id or branch:
            raise ValueError(
                'When --local option is set, --branch or --build cannot be '
                'specified.')
        elif not os.path.isdir(local_path):
            raise RuntimeError(
                'The specified local directory, {}, does not exist.'.format(
                    local_path))
    else:
        if not (build_id and branch):
            raise ValueError(
                'Please provide both --branch and --build or set --local '
                'option.')

    install_dir = os.path.join(PREBUILTS_VNDK_DIR, 'v{}'.format(vndk_version))
    if not os.path.isdir(install_dir):
        raise RuntimeError(
            'The directory for VNDK snapshot version {ver} does not exist.\n'
            'Please request a new git project for prebuilts/vndk/v{ver} '
            'before installing new snapshot.'.format(ver=vndk_version))

    utils.set_logging_config(verbose)
    root_dir = os.getcwd()
    os.chdir(install_dir)

    if not use_current_branch:
        start_branch(build_id)

    remove_old_snapshot(install_dir)
    os.makedirs(utils.COMMON_DIR_PATH)

    temp_artifact_dir = None
    if not local_path:
        temp_artifact_dir = tempfile.mkdtemp()

    try:
        install_snapshot(branch, build_id, local_path, install_dir,
                         temp_artifact_dir)
        gather_notice_files(install_dir)
        post_processe_files_if_needed(vndk_version)

        buildfile_generator = GenBuildFile(install_dir, vndk_version)
        update_buildfiles(buildfile_generator)

        copy_owners(root_dir, install_dir)

        if not local_path and not branch.startswith('android'):
            license_checker = GPLChecker(install_dir, ANDROID_BUILD_TOP,
                                         temp_artifact_dir, remote)
            check_gpl_license(license_checker)
            logging.info(
                'Successfully updated VNDK snapshot v{}'.format(vndk_version))
    except Exception as error:
        logging.error('FAILED TO INSTALL SNAPSHOT: {}'.format(error))
        raise
    finally:
        if temp_artifact_dir:
            logging.info(
                'Deleting temp_artifact_dir: {}'.format(temp_artifact_dir))
            shutil.rmtree(temp_artifact_dir)

    if not local_path:
        commit(branch, build_id, vndk_version)
        logging.info(
            'Successfully created commit for VNDK snapshot v{}'.format(
                vndk_version))

    logging.info('Done.')


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'vndk_version',
        type=utils.vndk_version_int,
        help='VNDK snapshot version to install, e.g. "{}".'.format(
            utils.MINIMUM_VNDK_VERSION))
    parser.add_argument('-b', '--branch', help='Branch to pull build from.')
    parser.add_argument('--build', help='Build number to pull.')
    parser.add_argument(
        '--local',
        help=('Fetch local VNDK snapshot artifacts from specified local '
              'directory instead of Android Build server. '
              'Example: --local=/path/to/local/dir'))
    parser.add_argument(
        '--use-current-branch',
        action='store_true',
        help='Perform the update in the current branch. Do not repo start.')
    parser.add_argument(
        '--remote',
        default='aosp',
        help=('Remote name to fetch and check if the revision of VNDK snapshot '
              'is included in the source to conform GPL license. default=aosp'))
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help='Increase output verbosity, e.g. "-v", "-vv".')
    return parser.parse_args()


def main():
    """Program entry point."""
    args = get_args()
    run(args.vndk_version, args.branch, args.build, args.local,
        args.use_current_branch, args.remote, args.verbose)


if __name__ == '__main__':
    main()
