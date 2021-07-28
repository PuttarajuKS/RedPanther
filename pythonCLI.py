#!/usr/bin/python2

import os
import io
import sys
import stat
import socket
import filecmp
import logging
import subprocess
import tempfile
from xml.sax import handler, parseString, parse
from common import *
from cpk import get_cpk_issues
import pygit2
import codecs
from version import *


def suggestIssues(ws_top, server, auth_opt=''):
    info = InfoParser(ws_top, server, auth_opt)
    data = get_cpk_issues(info._depot, info._ws_name, info._principal, server, auth_opt, show_gui=False)

    issues = data.get("issues", [])
    # log_to_file(issues)

    if len(issues) == 0:
        msg = 'No issues matching the Change Package criteria available for push.\n'
        return msg

    pty3_info = data.get("pty3_info", {})
    map_name_label = data.get("map_name_label", {})
    hasPty3Key = False
    if (pty3_info.get("ptyKey", "") != "issueNum"):
        hasPty3Key = True
        ptyKey = pty3_info.get("ptyKey")

    msg = 'Choose one of the issue(s) below and push again with \'-o cpk:<issue#>\'\n'
    for issue in issues:
        msg += '  {}:'.format(issue.get('issueNum'))
        shortDescription = issue.get('shortDescription', '')
        if hasPty3Key:
            pty3_num = issue.get(ptyKey, None)
            if pty3_num:
                msg += ' [{}]'.format(pty3_num)
        if shortDescription:
            suffix = '...' if len(shortDescription) > 35 else ''
            shortDescription = shortDescription.replace('\n', ' ')[:35] + suffix
            msg += ' {}'.format(shortDescription)
        msg += '\n'

    return msg

def toGit(s):
	print(s)
	#logging.debug('[to git]: {}'.format(s))

def toStdErr(msg):
    sys.stderr.write(msg)
    sys.stderr.flush()

def is_ancestor(commit_1, commit_2):
    # returns True if commit_1 is an ancestor of commit_2
    _, _, ret = run_cmd('git merge-base --is-ancestor {} {}'.format(commit_1, commit_2))
    return ret == 0

def get_update_trans_from_commit_message(depot, msg):
    if 'import from accurev @' in msg:
        # new format: import from accurev @ depot:trans
        #             [demote: files are demoted from ‘dev’]
        msg = msg.split('\n')[0]
        t = msg.split()[-1]
        if ':' in t:
            d, trans = t.split(':')
            if depot == d:
                return trans
        else:
            # old deprecated format: import from accurev @ trans: nnn
            display_accurev_error('Found commit message marker from an old and unsupported\n'
                                  'accurev git client. For best results, please clone again.\n')
            sys.exit(1)
    return ''

def get_initial_update_trans(ref, depot):
    # get the initial commit
    out, _, _ = run_cmd('git rev-list --max-parents=0 --oneline {}'.format(ref))
    # then parse out the update trans
    trans = get_update_trans_from_commit_message(depot, out)
    return trans

class UpdateParser(handler.ContentHandler):

    def __init__(self, ws_top, reroot, server, auth_opt='', show_progress=False):
        self._server = server
        self._auth_opt = auth_opt  # to impersonate a user
        self._tag = ''
        self._message = ''
        self._action = ''
        self._element = ''
        self._has_incoming_changes = False
        self._elem_list = []

        self._mark = 1
        self._ws_top = ws_top
        self._root = ''
        self._reroot = reroot

        # for progress
        self._number = 0
        self._checkpoint = 0
        self._progress = '-Z ' if show_progress else ''
        self._phase = ''
        self._temp = 100

    def __repr__(self):
        repStr  = '\t_server:  {}\n'.format(self._server)
        repStr += '\t_tag:     {}\n'.format(self._tag)
        repStr += '\t_message: {}\n'.format(self._message)
        repStr += '\t_action:  {}\n'.format(self._action)
        repStr += '\t_element: {}\n'.format(self._element)
        repStr += '\t_mark:    {}\n'.format(self._mark)
        repStr += '\t_ws_top:  {}\n'.format(self._ws_top)
        repStr += '\t_root:    {}\n'.format(self._root)
        repStr += '\t_reroot:  {}\n'.format(self._reroot)
        repStr += '\t_elem_list:['
        for i in self._elem_list:
            repStr += '\n\t{}'.format(i)
        repStr += '\t]\n'
        repStr += '\t_has_incoming_changes: {}\n'.format(self._has_incoming_changes)
        return repStr

    def execute(self, cmdline):
        run_ac_async(cmdline, lambda f: parse(f, self), self._server, self._auth_opt)

    def do_update_preview(self):
        self.execute('update -fx -i -L {}'.format(self._ws_top))

    def do_update(self, root):
        self._root = root
        self.execute('update -fx {}-L {}'.format(self._progress, self._ws_top))

    def do_update_with_trans(self, root, trans):
        self._root = root
        self.execute('update -fx -t {} -L {}'.format(trans, self._ws_top))

    def do_incl(self, path):
        self._root = path
        self.execute('incl -fx {}-L {} "{}"'.format(self._progress, self._ws_top, path))

    def do_pop(self, root):
        self._root = root
        self.execute('pop -fx {}-L {} -O -R /./'.format(self._progress, self._ws_top))

    def startElement(self, name, attr):
        #logging.debug('startElement(name: {}, attr: {}'.format(name, attr))
        self._tag = name

        if name == 'message':
            self._message = ''
        elif name == 'element':
            self._element = attr.getValue('location').strip('/\\').encode('utf-8')
        elif name == 'progress':
            self._phase = attr.get('phase', '')
            if self._phase == 'results':
                self._number = int(attr.get('number', 0))
                self._checkpoint = 0
                #toStdErr('\r{}'.format(' ' * 52))
        elif name == 'checkpoint':
            if not self._phase.startswith('Scanning for recently touched elements'):
                self._checkpoint += 1
                if self._checkpoint <= self._number:
                    # on pull
                    pct = (float(self._checkpoint) / self._number) * 100
                    toStdErr("\rReceiving objects: {}% ({}/{})".format(int(pct), self._checkpoint, self._number))
                elif not self._number:
                    # clone
                    if self._checkpoint >= self._temp:
                        self._temp *= 2
                    pct = (float(self._checkpoint) / self._temp) * 100
                    toStdErr("\rReceiving objects: {}% ({}/{})".format(int(pct), self._checkpoint, self._temp))

    def characters(self, ch):
        if self._tag == 'message':
            self._message += ch

    def endElement(self, name):
        #logging.debug('endElement(name: {})'.format(name))
        if name == 'message':
            if 'Create dir ' in self._message or 'Content (' in self._message or \
                'Updating' in self._message or 'Populating element' in self._message:
                self._action = 'add'
            elif 'Removing ' in self._message:
                self._action = 'delete'
            elif 'Moving ' in self._message:
                self._action = '' # to bypass the end of element action
                msg = self._message.split('"')
                src_name = msg[1].encode('utf-8')
                dst_name = msg[3].encode('utf-8')
                #self._element_list.append(('move', src_name, dst_name))
                self.update_one_element('move', src_name, dst_name)
            elif 'Would ' in self._message:
                #self._action = 'preview'
                self._action = ''
                self._has_incoming_changes = True

            #logging.debug(self._message.strip())
            self._message = ''
        elif name == 'element' and self._action != '':
            #self._element_list.append((self._action, self._element, ''))
            self.update_one_element(self._action, self._element, '')
            self._action = ''
            self._element = ''
        elif name == 'acResponse' or name == 'AcResponse':
            if self._progress and self._checkpoint > 0:
                toStdErr("\rReceiving objects: {}% ({}/{}), done.\n".format(100, self._checkpoint, self._checkpoint))

        self._tag = ''

    def update_one_element(self, op, file, file2):
        #logging.debug('update_one_element(op: {}, file: {}, file2: {}'.format(op, file, file2))
        # TODO: as file is of type <str>, converting root also to <str>. Need to consider it while changing it to XML code.
        if file == self._root.encode('utf-8') and op == 'move':
            self._root = file2
            return

        self._has_incoming_changes = True
        # path is now in file system encoding
        # not printable unless utf-8 encoded
        # path = r'{}'.format(os.path.join(r'{}'.format(self._ws_top.strip('"')), r'{}'.format(file))).decode('utf-8')
        path = os.path.join(self._ws_top.strip('"'), file).decode('utf-8')

        n = len(self._root) if self._reroot else 0
        file = file.replace('\\', '/')
        file = file[n:]
        file = file.strip('/')

        file2 = file2.replace('\\', '/')
        file2 = file2[n:]
        file2 = file2.strip('/')

        #logging.debug('op:{}; file:{}; path:{}'.format(op, file, path))
        if op == 'add':
            if os.path.isfile(path):
                if file == '.acsubmoduleIDs':
                    with open(path, 'rb') as f:
                        for l in f:
                            #logging.debug('.acsubmoduleIDs: {}'.format(l))
                            submod, shaID = l.split()
                            self._elem_list.append('M 160000 {} {}'.format(shaID, submod))
                    return
                toGit('blob')
                toGit('mark :{}'.format(self._mark))
                toGit('data {}'.format(os.path.getsize(path)))
                with open(path, 'rb') as f:
                    print(f.read())
                    # this prints the file contents to the log
                    # which can be excessive
                    #toGit(f.read())

                # M SP <mode> SP <dataref> SP <path> LF
                self._elem_list.append('M 100644 :{} {}'.format(self._mark, file))
                self._mark += 1

                try:
                    os.chmod(path, stat.S_IWRITE)
                    os.remove(path)
                except:
                    # failure to remove is not a critical error
                    # should just log it and move on
                    log_to_file('Failed to remove file: {}'.format(path.encode('utf-8')))

        elif op == 'delete':
            self._elem_list.append('D {}'.format(file))
        elif op == 'move':
            self._elem_list.append('R "{}" "{}"'.format(file, file2))

class UpdateTransParser(handler.ContentHandler):
    def __init__(self, server, auth_opt=''):
        self._update_trans = {}
        # for a proxy end user, on passing the auth token it fetches only that user's wspaces instead of
        # all wspaces. So, we use '-a' option to get all wspaces.
        run_ac_async('show -fix{} wspaces'.format(' -a' if auth_opt else ''), lambda f: parse(f, self), server, auth_opt)

    def startElement(self, name, attr):
        if name == 'Element':
            ws_name = attr.getValue('Name')
            self._update_trans[ws_name] = attr.getValue('Trans')

    def get_update_trans(self, ws_name):
        return self._update_trans.get(ws_name)

    def characters(self, ch):
        pass
    def endElement(self, name):
        pass


class TransHistParser(handler.ContentHandler):
    # get the hist of a transaction (who, when, what and maybe why) to use in git blame
    def __init__(self, trans, depot, server, auth_opt=''):
        self.time = ''
        self.user = ''
        self.type = ''
        self.comment = ''
        self.isComment = False
        run_ac_async('hist -ftx -t {} -p {}'.format(trans, depot), lambda f: parse(f, self), server, auth_opt)

    def startElement(self, name, attr):
        self._tmp_tag = name
        # log_to_file('name: {}, type: {}'.format(name, self.type))
        if name == 'transaction':
            self.type = attr.getValue('type')
            self.time = attr.getValue('time')
            self.user = attr.getValue('user')
        elif name == 'comment':
            self.isComment = True
            self.comment = ''
        elif name == 'stream' and self.type == 'chstream':
            name = attr.getValue('name')
            comment = ''

            try:
                basis = attr.getValue('basis')
                prevBasis = attr.getValue('prevBasis')
                comment += 'reparented from \'{}\' to \'{}\''.format(prevBasis, basis)
                log_to_file('prevBasis: {}, basis: {}'.format(prevBasis, basis))
            except:
                pass

            try:
                basis_time = attr.getValue('time')
                prevTime = attr.getValue('prevTime')
                log_to_file('prevTime: {}, time: {}'.format(prevTime, time))
                if comment:
                    comment += '; '
                comment += 'changed time basis from \'{}\' to \'{}\''.format(prevTime, basis_time)
            except:
                pass

            if comment:
                comment += '.'

            self.comment = 'Stream \'{}\' {}'.format(name, comment)
            log_to_file('comment: {}'.format(comment))
            log_to_file('self.comment: {}'.format(self.comment))

    def characters(self, ch):
        if self.isComment:
            self.comment += ch

    def endElement(self, name):
        if name == 'comment':
            self.isComment = False


class StatusParser(handler.ContentHandler):
    def __init__(self, list_path, ws_top, server, auth_opt=''):
        self._list_path = list_path
        self._ws_top = ws_top
        self._server = server
        self._auth_opt = auth_opt
        self._elem_list = []

    def execute(self, cmdline):
        run_ac_async(cmdline, lambda f: parse(f, self), self._server, self._auth_opt)

    def get_defunct_files(self):
        self.execute('stat -D -fx -l {} -L {}'.format(self._list_path, self._ws_top))

    def get_external_files(self):
        self.execute('stat -x -fx -l {} -L {}'.format(self._list_path, self._ws_top))

    def get_purge_list(self):
        self.execute('stat -k -fx -L {}'.format(self._ws_top))

    def startElement(self, name, attr):
        if name == 'element':
            location = attr.getValue('location')
            status = attr.getValue('status')
            self._elem_list.append((location, status))

    def characters(self, ch):
        pass

    def endElement(self, name):
        pass


class WspaceParser(handler.ContentHandler):
    def __init__(self, depot, ws_top, server, auth_opt=''):
        self._wspaces = set()
        self._principal = ''
        self._ws_top = ws_top.replace('\\', '/').strip('"')
        self._ws_drive, self._ws_path = os.path.splitdrive(self._ws_top)
        self._ws_drive = self._ws_drive.lower()
        self._depot = depot
        self._reusable_ws = ''
        self._reusable_ws_hidden = False
        self._host = socket.gethostname()
        self._server = server
        self._auth_opt = auth_opt
        #logging.debug('incoming ws_top={}'.format(ws_top))
        #logging.debug('WspaceParser._ws_top={}'.format(self._ws_top))
        #logging.debug('target: host={}, depot={}, drive={}, path={}'.format(self._host, self._depot, self._ws_drive, self._ws_path))
        run_ac_async('show -fix wspaces', lambda f: parse(f, self), self._server, self._auth_opt)

    def __repr__(self):
        repStr  = '\t_wspaces: {}\n'.format(self._wspaces)
        repStr += '\t_principal: {}\n'.format(self._principal)
        repStr += '\t_ws_top: {}\n'.format(self._ws_top)
        repStr += '\t_ws_path: {}\n'.format(self._ws_path)
        repStr += '\t_ws_drive: {}\n'.format(self._ws_drive)
        repStr += '\t_depot: {}\n'.format(self._depot)
        repStr += '\t_reusable_ws: {}\n'.format(self._reusable_ws)
        repStr += '\t_reusable_ws_hidden: {}\n'.format(self._reusable_ws_hidden)
        repStr += '\t_host: {}\n'.format(self._host)
        return repStr

    def startElement(self, name, attr):
        if name == 'Element':
            ws_name = attr.getValue('Name')
            self._principal = attr.getValue('user_name')

            host = attr.getValue('Host')
            storage = attr.getValue('Storage').replace('\\', '/')
            drive, path = os.path.splitdrive(storage)
            drive = drive.lower()
            depot = attr.getValue('depot')
            hidden = ('true' == attr.get('hidden'))
            match = (host == self._host and depot == self._depot and
                     drive == self._ws_drive and path == self._ws_path)
            #logging.debug('host={}, depot={}, drive={}, path={}'.format(host, depot, drive, path))
            if match and not (self._reusable_ws and not self._reusable_ws_hidden):
                # replace the previous match if it was hidden
                if self._reusable_ws:
                    self._wspaces.add(self._reusable_ws)

                self._reusable_ws = ws_name
                self._reusable_ws_hidden = hidden
            else:
                # either not a match or already found a non-hidden match
                self._wspaces.add(ws_name)

    def characters(self, ch):
        pass
    def endElement(self, name):
        pass
    def get_unique_name(self, stream, alias):
        # if no wspaces are created by this principal then parser cannot compute the principal name.
        # so we gotta issue a 'info' cmd to get principal.
        if(self._principal == ''):
            info = InfoParser('', self._server, self._auth_opt, get_principal=True)
            self._principal = info.get_principal()

        ws_name = '{}.{}_{}'.format(stream, alias, self._principal)
        n = 1
        while ws_name in self._wspaces:
            ws_name = '{}.{}.{}_{}'.format(stream, alias, n, self._principal)
            n += 1
        
        return ws_name


class DetectModParser(handler.ContentHandler):
    def __init__(self, direct_anc, merge_anc, elem_list, temp_mod, ws_top, server, auth_opt=''):
        self._direct_anc = direct_anc
        self._merge_anc = merge_anc
        self._temp_mod = temp_mod
        self._n = 0

        out = run_ac('stat -fex -l {} -L {}'.format(elem_list, ws_top), server, auth_opt)
        out = out.encode('utf-8')
        parseString(out, self)

    def startElement(self, name, attr):
        if name == 'element':
            status = attr.getValue('status')
            if '(modified)' in status:
                eid = attr.getValue('id')
                self._temp_mod.write('<element\n')
                self._temp_mod.write('eid="{}"\n'.format(eid))
                if eid in self._direct_anc:
                    anc_stream, anc_ver = self._direct_anc[eid]
                else:
                    # direct anc is not specified, use the current workspace version
                    # leaving this un-specified and use a merge anc will sometimes cause
                    # accurev server to reverse the two ancestors!!!
                    ver = attr.getValue('Real')
                    anc_stream, anc_ver = ver.replace('\\', '/').split('/')
                self._temp_mod.write('anc_stream = "{}"\n'.format(anc_stream))
                self._temp_mod.write('anc_ver = "{}">\n'.format(anc_ver))
                # logging.debug('eid: {}, anc_stream: {}, anc_ver: {}'.format(eid, anc_stream, anc_ver))

                if eid in self._merge_anc:
                    merge_anc_stream, merge_anc_ver = self._merge_anc[eid]
                    self._temp_mod.write('<segments><segment\n')
                    self._temp_mod.write('head = "{}/{}"\n'.format(merge_anc_stream, merge_anc_ver))
                    self._temp_mod.write('/></segments>\n')
                self._temp_mod.write('</element>\n')
                self._n += 1

    def characters(self, content):
        pass

    def endElement(self, name):
        pass


class ElemVersParser(handler.ContentHandler):
    # for getting the version for the specified elements
    def __init__(self, trans, stream, elem_list, server, auth_opt=''):
        self._trans = 'now' if not trans else trans
        self._elem_ver = {}

        out = run_ac('stat -fex -t {} -s "{}" -l {}'.format(self._trans, stream, elem_list), server, auth_opt)
        out = out.encode('utf-8')
        parseString(out, self)

    def startElement(self, name, attr):
        if name == 'element':
            status = attr.getValue('status')
            if status != '(no such elem)':
                eid = attr.getValue('id')
                ver = attr.getValue('Real')
                if eid and ver:
                    anc_stream, anc_ver = ver.replace('\\', '/').split('/')
                    self._elem_ver[eid] = (anc_stream, anc_ver)
                    #logging.debug('[from ElemVer] eid = {}, version = {}'.format(eid, ver))

    def characters(self, content):
        pass

    def endElement(self, name):
        pass


class HistExistsParser(handler.ContentHandler):
    # tells whether the keep has been done for a commit or not
    def __init__(self, commit_id, ws_name, server, auth_opt=''):
        self.hist_exists = False
        out = run_ac('hist -s "{}" -c {} -fx -a'.format(ws_name, commit_id), server, auth_opt)
        out = out.encode('utf-8')
        parseString(out, self)

    def startElement(self, name, attr):
        if name == 'transaction':
            self.hist_exists = True

    def characters(self, ch):
        pass

    def endElement(self, name):
        pass


class HistParser(handler.ContentHandler):
    # this figures out the last weorkspace version for the specified elements
    def __init__(self, commit_id, stream, elem_list, server, auth_opt=''):
        self._elem_ver = {}
        self._eid = ''
        self._version = ''
        query = '-c {}'.format(commit_id) if commit_id else '-tnow'
        out, err, ret = run_ac_ignore_error('hist -s "{}" {} -fx -l {}'.format(stream, query, elem_list), server, auth_opt)
        # sometimes the elem might not be there and we get an error
        # e.g. No element named /git_automation/__ac_cli_lib__/Action.pyc
        if ret != 0:
            NO_ELEMENT_NAMED = 'No element named'
            if err.startswith(NO_ELEMENT_NAMED):
                elems = ''
                with open(elem_list, 'r') as f:
                    elems = f.read().lstrip(codecs.BOM_UTF8)  # remove the UTF-8 encoding at the beginning of file
                elems = elems.split('\n')
                unfound_elems = err.split('\n')
                log_to_file('[Unfound elements]: {}'.format(unfound_elems))
                log_to_file('[elems]: {}'.format(elems))
                # 'No element named /' (additional length + 2, for space and backslash)
                start_index = len(NO_ELEMENT_NAMED) + 2
                for elem in unfound_elems:
                    if elem.startswith(NO_ELEMENT_NAMED):
                        elem = elem[start_index:].strip()
                        if elem in elems:
                            elems.remove(elem)

                # remove empty elements from list
                elems = [i for i in elems if i.strip()]
                log_to_file('[updated elems]: {}'.format(elems))
                if elems:
                    temp_list = tempfile.NamedTemporaryFile(delete=False)
                    temp_list.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
                    for elem in elems:
                        temp_list.write('{}\n'.format(elem.strip()))
                    temp_list.close()
                    out = run_ac('hist -s "{}" {} -fx -l {}'.format(stream, query, temp_list.name), server, auth_opt)
                else:
                    return # since no elements
            else:
                display_accurev_error(err)
                sys.exit(1)

        out = out.encode('utf-8')
        parseString(out, self)

    def startElement(self, name, attr):
        if name == 'element':
            self._eid = attr.getValue('id')
        elif name == 'version':
            if not self._version:
                self._version = attr.getValue('real')
    def characters(self, ch):
        pass
    def endElement(self, name):
        if name == 'element':
            if self._version:
                anc_stream, anc_ver = self._version.replace('\\', '/').split('/')
                self._elem_ver[self._eid] = (anc_stream, anc_ver)
                #logging.debug('[from hist] eid = {}, version = {}'.format(self._eid, self._version))
            self._eid = ''
            self._version = ''

class RulesParser(handler.ContentHandler):
    def __init__(self, stream, server, auth_opt=''):
        self._elements = []
        self._incl_location = ''
        out = run_ac('lsrules -s "{}" -d -fx'.format(stream), server, auth_opt)
        if out:
            parseString(out, self)

    def startElement(self, name, attr):
        if name == 'element':
            location = attr.getValue('location')
            self._elements.append(location)
            kind = attr.getValue('kind')
            if kind == 'incl':
                self._incl_location = location

    def characters(self, ch):
        pass
    def endElement(self, name):
        pass

class StreamParser(handler.ContentHandler):
    def __init__(self, stream, server, auth_opt=''):
        self._depot = ''
        out = run_ac('show -fx -s "{}" streams'.format(stream), server, auth_opt)
        parseString(out, self)

    def startElement(self, name, attr):
        if name == 'stream':
            self._depot = attr.getValue('depotName')
    def characters(self, ch):
        pass
    def endElement(self, name):
        pass

class RemoteParser(object):
    def __init__(self, alias, url):
        self._server = ''
        self._stream = ''
        self._path = ''
        self._reroot = False
        self.parse_url(url)
        #logging.debug('RemoteParser: path: {}, re-root: {}'.format(self._path, self._reroot))

        # 'git ls-remote accurev::<url>' will invoke us with alias being accurev::<url>
        self._alias = self._stream if '://' in alias else alias

        self._blob = {} # dictionary
        self._marks = {} # git marks
        self._submods = {} # submodule SHAs
        self._commit_shas = {} # epoch_time to commit_sha
        self._prefix = 'refs/accurev/%s' % self._alias
        self._ws_top = ''
        self._git_marks = '' # path to the git mark file
        self._submodIDs = '' # path to submodule ID file
        self._git_marks_loaded = False
        self._commit_shas_loaded_from_time = False
        self._tmp_git_marks_loaded = False
        self._tmp_git_marks = '' # path to temp git mark file
        self._gitdir = os.environ.get('GIT_DIR', None)
        self._show_progress = False
        self._trigger_promote = False # set True if op performed is either defunct / move / add / keep
        self._push_option = '' # set Issue number through "git push --push-option=cpk:123"
        self._target_trans = '' # get the transaction, that causes change in event stream through trigger
        self._auth_token = '' # to impersonate a user
        self._auth_opt = ''
        self._promote_comment = '' # file with promote comment(s)
        self._isCPKGuiDisabled = False
        if self._gitdir:
            self._gitdir = os.path.realpath(self._gitdir) # always use a full path
            self._gitdir = r'{}'.format(self._gitdir)
            # ws top is '.git/accurev/<alias>'
            self._ws_top = r'"{}"'.format(os.path.join(self._gitdir, r'accurev/{}'.format(self._alias)))
            self._git_marks = r'{}'.format(os.path.join(self._ws_top.strip('"'), r'.accurev/git-marks'))
            self._submodIDs = r'{}'.format(os.path.join(self._ws_top.strip('"'), r'.acsubmoduleIDs'))
            self._tmp_git_marks = r'{}'.format(os.path.join(self._ws_top.strip('"'), r'.accurev/git-marks.tmp'))
            log_to_file('GIT_DIR=%s, WS_TOP=%s, GIT marks=%s' % (self._gitdir, self._ws_top, self._git_marks))
            self._repo = pygit2.Repository(self._gitdir)

            auth_file_dir = self._gitdir.replace('\\', '/')
            auth_file = os.path.join(os.path.dirname(auth_file_dir), 'data/authtoken')
            auth_file = auth_file.replace('\\', '/')
            log_to_file('[authfile]: {}'.format(auth_file))

            # CPK GUI is disabled only if the repo is 'proxy' bare repo. If it is a clone and being done inside
            # staging directory which has authtoken, then use auth token
            self._isCPKGuiDisabled = get_git_config('accurev.cpkgui.disable', repo=self._repo) == 'true'
            if(self._isCPKGuiDisabled or os.path.exists(auth_file)):
                # 'git push' explicitly set's an Auth token to impersonate user
                # if no Auth token is found (could be 'git fetch') then read it from /STAGING_FOLDER/DATA/authtoken file
                self._auth_token = get_git_config('accurev.user.authtoken', self._repo)
                if self._auth_token:
                    log_to_file('[authtoken]: {}'.format(self._auth_token))
                    self._auth_opt = '-A {} '.format(self._auth_token)
                else:
                    if os.path.isfile(auth_file) and os.path.exists(auth_file):
                        with open(auth_file) as file:
                            self._auth_token = file.read().strip()
                            if self._auth_token:
                                log_to_file('[authtoken]: {}'.format(self._auth_token))
                                self._auth_opt = '-A {} '.format(self._auth_token)

    def __repr__(self):
        repStr  = '\t_server:    {}\n'.format(self._server)
        repStr += '\t_stream:    {}\n'.format(self._stream)
        repStr += '\t_path:      {}\n'.format(self._path)
        repStr += '\t_reroot:    {}\n'.format(self._reroot)
        repStr += '\t_blob:{'
        for i in sorted(self._blob):
            repStr += '\n    {}: {}'.format(i, self._blob[i])
        repStr += '\t}\n'
        repStr += '\t_submods:{'
        for i in sorted(self._submods):
            repStr += '\n    {}: {}'.format(i, self._submods[i])
        repStr += '\t}\n'
        repStr += '\t_prefix:    {}\n'.format(self._prefix)
        repStr += '\t_gitdir:    {}\n'.format(self._gitdir)
        repStr += '\t_ws_top:    {}\n'.format(self._ws_top)
        repStr += '\t_git_marks: {}\n'.format(self._git_marks)
        repStr += '\t_submodIDs: {}\n'.format(self._submodIDs)
        repStr += '\t_repo:      {}\n'.format(self._repo)
        repStr += '\t_marks:{'
        for i in sorted(self._marks):
            repStr += '\n    {}: {}'.format(i, self._marks[i])
        repStr += '\t}\n'
        repStr += '\t_tmp_git_marks: {}\n'.format(self._tmp_git_marks)
        repStr += '\t_git_marks_loaded: {}\n'.format(self._git_marks_loaded)
        repStr += '\t_tmp_git_marks_loaded: {}\n'.format(self._tmp_git_marks_loaded)
        return repStr

    def parse_url(self, url):
        '''
        git clone accurev://<host>:<port>/stream[/path/to/repo]

        examples:
        git clone accurev://alpo:5050/ac_complete
        git clone accurev://alpo:5050/ac_complete/programs/server
        - The port number will not be at the end in all cases
        - hostname, port and stream part are required
        - /path/to/repo specifies sub-namespace

        git ls-remote accurev://<url> will invoke us with alias as accurev://<url> and url as accurev://<url>
        while git clone accurev://<url> will invoke us with alias as origin and url <url>
        '''

        if '://' not in url:
            display_url_error()
            sys.exit(1)
        else:
            url = url.split('://')[1]

        log_to_file(message=url, level=Level.INFO, method='URL')
        try:
            self._server, url = url.split('/', 1)
        except:
            display_url_error()
            sys.exit(1)

        if not self._server or not url:
            display_url_error()
            sys.exit(1)

        if ':' in self._server:
            try:
                host, port = self._server.split(':')
            except ValueError:
                display_accurev_error('melformed host:port in url\n')
                display_url_error()
                sys.exit(1)
            if not host or not port or not port.isdigit():
                display_accurev_error('melformed host:port in url\n')
                display_url_error()
                sys.exit(1)
        else:
            display_accurev_error('melformed host:port in url\n')
            display_url_error()
            sys.exit(1)

        if '/' in url:
            tokens = url.split('/', 1)
            url = tokens[0]
            self._path = tokens[1]
            self._path = self._path.replace('\\', '/')
            self._reroot = self._path.startswith('//')
            self._path = self._path.strip('/')
            if not self._path:
                self._reroot = False

        self._stream = url
        if not self._stream:
            display_accurev_error('melformed stream in url\n')
            display_url_error()
            sys.exit(1)

    def get_line(self):
        self._line = sys.stdin.readline().strip()
        log_to_file('[from git]: %s' % self._line)
        return self._line

    def check(self, word):
        return self._line.startswith(word)

    def normalizePath(self, path):
        path = path.replace('\\', '/').strip()
        if path.startswith('./'):
            path=path[2:]
        return path

    def __getitem__(self, i):
        return self._line.split()[i]

    def __iter__(self):
        return self
        
    def next(self):
        return self.get_line()

    def parse_mark(slef, line):
        return line.split(':')[1]

    def parse_data(self, line):
        size = int(line.split(' ')[1])
        return sys.stdin.read(size)
    
    def parse_blob(self):
        line = self.next() # mark
        mark = self.parse_mark(line)

        line = self.next() # data
        self._blob[mark] = self.parse_data(line)
        self.next() # blank line

    def addSubID(self, file, shaID):
        # read "file sha" lines into dictionary
        if os.path.isfile(self._submodIDs):
            with open(self._submodIDs) as f:
                IDs = {x[0]:x[1] for x in [l.strip().split() for l in f]}
        else:
            IDs = {}
        IDs[file] = shaID	# create or update the file entry
        with open(self._submodIDs, 'wb') as f:
            for name, id in IDs.items():
                f.write('{} {}\n'.format(file, shaID))
        f.close()

    def detect_move(self, defunct_list, full_path):
        for old_path in defunct_list:
            # full_old_path = r'{}'.format(os.path.join( r'{}'.format(self._ws_top.strip('"')), r'{}'.format(old_path)))
            full_old_path = os.path.join(self._ws_top.strip('"'), old_path.decode('utf8'))
            if filecmp.cmp(full_old_path, full_path, shallow=False):
                return old_path
        return ''
    
    def exec_op(self, op, elem_list, comments):
        if not elem_list:
            return
    
        temp = tempfile.NamedTemporaryFile(delete=False)
        temp.write(codecs.BOM_UTF8) # changes the file to UTF-8-BOM
        for path in elem_list:
            temp.write(path + '\n')
        temp.close()

        if op == 'add':
            out, err, ret = run_ac_ignore_error('{} -c @{} -l {} -L {}'.format(op, comments, temp.name, self._ws_top), self._server, self._auth_opt)
            if ret != 0:
                ELEMENT_ALREADY_EXISTS = 'Element already exists:'
                if err.startswith(ELEMENT_ALREADY_EXISTS):
                    # these files are already added, so we remove it from the elem_list and 'add' them again
                    # e.g. Element already exists: /git_automation/git_cpk/smoke/common/One_trigger-One_trigger_condition-Multiple_queries.xml
                    added_files = err.split('\n')
                    log_to_file('[already added files]: {}'.format(added_files))
                    log_to_file('[element list]: {}'.format(elem_list))
                    # Element already exists: / (include space & backslash length)
                    start_index = len(ELEMENT_ALREADY_EXISTS) + 2
                    for elem in added_files:
                        if elem.startswith(ELEMENT_ALREADY_EXISTS):
                            elem = elem[start_index:].strip()
                            if elem in elem_list:
                                elem_list.remove(elem)
                    os.remove(temp.name)
                    # remove empty elements from list
                    elem_list = [i for i in elem_list if i.strip()]
                    log_to_file('[updated element list]: {}'.format(elem_list))
                    if elem_list:
                        temp = tempfile.NamedTemporaryFile(delete=False)
                        temp.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
                        for path in elem_list:
                            temp.write(path + '\n')
                        temp.close()
                        run_ac('{} -c @{} -l {} -L {}'.format(op, comments, temp.name, self._ws_top), self._server, self._auth_opt)
                    else:
                        # no elem to be 'added'
                        return
                else:
                    display_accurev_error(err)
                    sys.exit(1)
        else:
            run_ac('{} -c @{} -l {} -L {}'.format(op, comments, temp.name, self._ws_top), self._server, self._auth_opt)

        self._trigger_promote = True # add or defunct op
        try:
            os.remove(temp.name)
        except:
            pass

    def load_marks_from_file(self, filename):
        log_to_file('loading marks from file: {}'.format(filename))
        with open(filename) as marks:
            for mark in marks:
                m, h = mark.split()
                self._marks[m.strip()] = h.strip()
                logging.debug('mark {}, commit_sha {}'.format(m.strip(), h.strip()))

    def load_git_marks(self):
        if not self._git_marks_loaded:
            self.load_marks_from_file(self._git_marks)
            self._git_marks_loaded = True

        if not self._tmp_git_marks_loaded and os.path.exists(self._tmp_git_marks):
            self.load_marks_from_file(self._tmp_git_marks)
            self._tmp_git_marks_loaded = True

    def get_stream_elem_vers(self, commit_trans, stream, elem_list):
        elem_vers_parser = ElemVersParser(commit_trans, stream, elem_list, self._server, self._auth_opt)
        return elem_vers_parser._elem_ver

    def get_commit_elem_vers(self, depot, commit_mark, elem_list):
        if commit_mark:
            commit_id = ''
            if commit_mark in self._marks:
                commit_id = self._marks[commit_mark]
                # Using pygit2 instead of 'git log' cmd
                # out, _, _ = run_cmd('git log --format=%B -n 1 {}'.format(commit_id))
                commit = self._repo.get(commit_id, None)
                out = commit.message if commit else ''
                trans = get_update_trans_from_commit_message(depot, out)
                if trans:
                    return self.get_stream_elem_vers(trans, self._stream, elem_list)

            ws_name = get_git_config('accurev.{}.wsname'.format(self._alias), repo=self._repo)
            hist = HistParser(commit_id, ws_name, elem_list, self._server, self._auth_opt)
            return hist._elem_ver
        else:
            # the commit from: mark is missing for the 1st push!!!
            # the basis is alwyas the clone transaction
            trans = get_initial_update_trans('{}/heads/master'.format(self._prefix), depot)
            return self.get_stream_elem_vers(trans, self._stream, elem_list)

    def do_keeps(self, depot, keep_list, comment, commit_from_mark, merge_from_mark):
        if not keep_list:
            return

        temp = tempfile.NamedTemporaryFile(delete=False)
        temp.write(codecs.BOM_UTF8)
        for elem in keep_list:
            temp.write('{}\n'.format(elem.strip()))
        temp.close()

        direct_anc = self.get_commit_elem_vers(depot, commit_from_mark, temp.name)
        merge_anc = {}
        if merge_from_mark:
            merge_anc = self.get_commit_elem_vers(depot, merge_from_mark, temp.name)

        # run the stat to detect modified files
        temp_mod = tempfile.NamedTemporaryFile(delete=False, mode='w+b')
        temp_mod.write('<elements>\n')
        detect_mod_parser = DetectModParser(direct_anc, merge_anc, temp.name, temp_mod, self._ws_top, self._server, self._auth_opt)
        temp_mod.write('</elements>\n')
        temp_mod.close()

        # Replacing cmd output with DetectModParser
        # out = run_ac('stat -fe -l {} -L {}'.format(temp.name, self._ws_top),
        #              self._server)
        os.remove(temp.name)

        if detect_mod_parser._n > 0:
            run_ac('keep -c @{} -Fx -l {} -L {}'.format(comment, temp_mod.name, self._ws_top), self._server, self._auth_opt)
            self._trigger_promote = True # keep op if files are modified
        os.remove(temp_mod.name)

    def get_all_commit_shas_since_time(self, epoch):
        out, _, _ = run_cmd('git --no-pager log --all --pretty=format:"%H %cd" --since="{}" --date=raw'.format(epoch))
        self._commit_shas_loaded_from_time = True
        for eachline in out.splitlines():
            commit_sha = eachline.split()[0]
            epoch = ' '.join(eachline.split()[1:])
            self._commit_shas[epoch] = commit_sha

    def parse_commit(self, depot, root, dry_run):
        # insome use cases, the tmp git marks file is not created
        # in time for the commit so we check and load the marks
        # if it has not been done
        self.load_git_marks()

        elem_list = [] # full list in its natural order
        tmp_comment = tempfile.NamedTemporaryFile(delete=False)
        # make the tmp_comment file as UTF-8 and add "@@Content-Encoding: utf-8"
        tmp_comment.write(codecs.BOM_UTF8)
        tmp_comment.write('@@Content-Encoding: utf-8\n')

        commit_sha = ''
        commit_from_mark = ''
        merge_from_mark = ''
        for line in self:
            if self.check('mark'):
                commit_mark = line.split()[1]
                commit_sha = self._marks.get(commit_mark)
                log_to_file('commit_sha obtained for commit_mark {} - {}'.format(commit_mark, commit_sha))
            elif self.check('author'):
                # ('author' (SP <name>)? SP LT <email> GT SP <when> LF)?
                epoch = '{} {}'.format(line.split()[-2], line.split()[-1])
                ac_time = epoch_time_to_accurev_time(int(epoch.split()[0]))
                comment = '[git commit]: {} {}\n'.format(' '.join(line.split()[:-2]), ac_time)
                tmp_comment.write(comment)
                #tmp_comment.write('[git commit]: {}\n'.format(line))
            elif self.check('committer'):
                # 'committer' (SP <name>)? SP LT <email> GT SP <when> LF
                epoch = '{} {}'.format(line.split()[-2], line.split()[-1])
                ac_time = epoch_time_to_accurev_time(int(epoch.split()[0]))
                comment = '[git commit]: {} {}\n'.format(' '.join(line.split()[:-2]), ac_time)
                tmp_comment.write(comment)

                if not commit_sha:
                    log_to_file('commit_sha not found, computing it from time')
                    # commit mark is not yet in the git marks file
                    # committer time should have a lower chance of collision
                    # than the author time
                    if not self._commit_shas_loaded_from_time:
                        self.get_all_commit_shas_since_time(epoch)
                    commit_sha = self._commit_shas.get(epoch)
                    log_to_file('commit_sha found from time: {}'.format(commit_sha))

                if commit_sha:
                    comment = '[git commit]: {}\n'.format(commit_sha)
                    tmp_comment.write(comment)
                    log_to_file('commit: {}'.format(commit_sha))
                else:
                    log_to_file('commit_sha not added to the KEEP comment. Failing this push.')
                    toGit('error refs/heads/master failed to get commit sha')
                    sys.exit(1)

            elif self.check('data'):
                comment = self.parse_data(line)
                tmp_comment.write(comment)
                self._promote_comment.write('[git commit]: {}'.format(comment))
            elif self.check('from'):
                # the from mark specifies the basis for this commit
                # which could fall in on eof the following
                # 1. a fetch commit which should be in the mark-file
                #       The basis version is the backing version at fetch trans
                #       current version in the workspace does not affect this basis
                # 2. a commit that has been previously pushed which should also be in the mark file
                #       The basis is the last workspace version
                #       current version in the workspace does not affect this basis
                # 3. a commit that is previously seen in this push which will not be in the mark file
                #       The basis is the current workspace version
                commit_from_mark = line.split()[1]
            elif self.check('merge'):
                # the merge mark follows the same logic as the commit mark above
                # seems like this might be an issue if merging between branches
                # rather than from the backing
                merge_from_mark = line.split()[1]
            elif line == '':
                break
            elif self.check('deleteall'):
                pass
            elif self.check('C '):
                # copy: 'C' SP <path> SP <path> LF
                elem_list.append(line)
            elif self.check('R '):
                # rename: 'R' SP <path> SP <path> LF
                elem_list.append(line)
            elif self.check('D '):
                # delete: 'D' SP <path> LF
                elem_list.append(line)
            elif self.check('M '):
                op, perm, mark, path = line.split(' ', 3)
                if perm == '160000':     # git submodule directory
                    self._submods[path] = mark
                # modify or add
                elem_list.append(line)
            else:
                log_to_file('unrecognized line in commit block: %s' % line)
        
        tmp_comment.close()
        
        if dry_run:
            # return empty commit SHA
            return ''

        # if commit_sha:
        #     ws_name = get_git_config('accurev.{}.wsname'.format(self._alias), repo=self._repo)
        #     histExistsParser = HistExistsParser(commit_sha, ws_name, self._server)
        #     if histExistsParser.hist_exists:
        #         return commit_sha

        # root is passed in now, so we will not call lsrules
        # once per commit
        #root = r'{}'.format(self.get_root())
        #logging.debug('root: {}'.format(root))
        #logging.debug('self: {}'.format(self))
        #logging.debug('elem_list: {}'.format(elem_list))

        # extract all deletes
        defunct_list = []
        add_keep_list = []
        for elem in elem_list:
            p = elem.split()
            op = p[0]
            if op == 'D':
                # delete: 'D' SP <path> LF
                _, path = elem.split(' ', 1)
                #path = p[1]
                path = c_style_unescape(path)
            elif op == 'M':
                # modify: 'M' SP <mode> SP <dataref> SP <path> LF
                # dataref: either a mark ref (:idnum) or SHA-1
                _, _, _, path = elem.split(' ', 3)
                #path = p[3]
                path = c_style_unescape(path)
            else:
                # other operations are not yet supported
                log_to_file('operation not supported: {}'.format(elem))
                continue

            if self._reroot:
                path = r'{}'.format(os.path.join(root, r'{}'.format(path)))
            elif not path.startswith(root):
                # changes from outside our namespace
                log_to_file('skipping {}'.format(r'{}'.format(path)))
                continue

            if op == 'D':
                defunct_list.append(r'{}'.format(path))
            else:
                mark = p[2].strip(':')
                #logging.debug('op = %s, mark = %s, path = %s' % (op, mark, r'{}'.format(path)))

                if p[1] == '160000':	# submodule
                    self.addSubID(path, mark)
                    subModIDFile = r'{}'.format(os.path.basename(self._submodIDs))
                    if subModIDFile not in add_keep_list:
                        add_keep_list.append(subModIDFile)
                    continue

                full_path = os.path.join(self._ws_top.strip('"'), path.decode('utf8'))
                add_keep_list.append(path)
                # git does not instruct us to create the directories
                # so we need to ensure that the path exists before writing to the file
                dir_path = os.path.dirname(full_path)
                make_sure_path_exists(dir_path)
                # with open(full_path, 'wb+') as f:
                #     f.write(self._blob[mark])
                with open(os.path.join(self._ws_top.strip('"'), path.decode('utf8')), 'wb+') as f:
                    f.write(self._blob[mark])

        if defunct_list:
            # since we don't keep the files around in the workspace
            # and files on this list are either to be defuncted
            # or to be renamed, so they need to be on disk
            tmp_pop = tempfile.NamedTemporaryFile(delete=False)
            tmp_pop.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
            for elem in defunct_list:
                tmp_pop.write('{}\n'.format(elem.strip()))
            tmp_pop.close()
            pop_out, pop_error, pop_ret = run_ac_ignore_error('pop -l {} -L {}'.format(tmp_pop.name, self._ws_top), self._server, self._auth_opt)
            if pop_ret != 0:
                NO_ELEMENT_NAMED = 'No element named'
                if pop_error.startswith(NO_ELEMENT_NAMED):
                    # these files are already defuncted, so we remove it from the defunct_list
                    # e.g. No element named /ProxyUI/src/app/data/aclGroupMembers.ts
                    defuncted_files = pop_error.split('\n')
                    log_to_file('[already defuncted files]: {}'.format(defuncted_files))
                    log_to_file('[defunct list]: {}'.format(defunct_list))
                    # No element named / (include space & backslash length)
                    start_index = len(NO_ELEMENT_NAMED) + 2
                    for elem in defuncted_files:
                        if (elem.startswith(NO_ELEMENT_NAMED)):
                            elem = elem[start_index:].strip()
                            if elem in defunct_list:
                                defunct_list.remove(elem)

                    # remove empty elements from list
                    defunct_list = [i for i in defunct_list if i.strip()]
                    log_to_file('[updated defunct list]: {}'.format(defunct_list))

                    os.remove(tmp_pop.name)
                    if defunct_list:
                        tmp_pop = tempfile.NamedTemporaryFile(delete=False)
                        tmp_pop.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
                        for elem in defunct_list:
                            tmp_pop.write('{}\n'.format(elem.strip()))
                        tmp_pop.close()
                        run_ac('pop -l {} -L {}'.format(tmp_pop.name, self._ws_top), self._server, self._auth_opt)
                else:
                    display_accurev_error(pop_error)
                    sys.exit(1)
            try:
                os.remove(tmp_pop.name)
            except:
                pass

        add_list = []
        keep_list = []
        if add_keep_list:
            tmp_stat = tempfile.NamedTemporaryFile(delete=False)
            tmp_stat.write(codecs.BOM_UTF8)
            for elem in add_keep_list:
                elem = self.normalizePath(elem)
                keep_list.append(elem)
                tmp_stat.write('{}\n'.format(elem))
            tmp_stat.close()

            #logging.debug(keep_list)

            # replacing cmd output with StatusParser
            status_parser = StatusParser(tmp_stat.name, self._ws_top, self._server, self._auth_opt)
            status_parser.get_external_files()
            out = status_parser._elem_list

            # out = run_ac('stat -x -l {} -L {}'.format(tmp_stat.name, self._ws_top),
            #              self._server)
            os.remove(tmp_stat.name)
            for elem in out:
                # new file or part of a rename
                # logging.debug(elem)
                path = elem[0]
                path = path.encode('utf-8')
                path = self.normalizePath(path)
                status = elem[1]
                full_path = os.path.join(self._ws_top.strip('"'), path.decode('utf8'))
                old_path = self.detect_move(defunct_list, full_path)
                # TODO: removing from a list is slow, have to find a different way to do this!!!

                # logging.debug('path = %s; old_path = %s; full_path = %s' % (path, old_path, full_path))
                if old_path:
                    os.remove(full_path)

                    # 'accurev xml -l tempfile' instead of cmd line
                    # to support Non-ASCII names
                    temp_move = tempfile.NamedTemporaryFile(delete=False)
                    temp_move.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    temp_move.write('<AcCommand command="move">\n')
                    if self._server:
                        temp_move.write('<arg>-H</arg>\n')
                        temp_move.write('<arg>{}</arg>\n'.format(self._server))
                    if self._auth_token:
                        temp_move.write('<arg>-A</arg>\n')
                        temp_move.write('<arg>{}</arg>\n'.format(self._auth_token))
                    temp_move.write('<arg>-L</arg>\n')
                    temp_move.write('<arg>{}</arg>\n'.format(self._ws_top.strip('"')))

                    temp_move.write('<arg>-c</arg>\n')
                    temp_move.write('<arg>@{}</arg>\n'.format(tmp_comment.name))

                    temp_move.write('<arg>{}</arg>\n'.format(old_path))
                    temp_move.write('<arg>{}</arg>\n'.format(path))
                    temp_move.write('</AcCommand>')

                    temp_move.close()
                    run_ac_xml(temp_move.name)
                    self._trigger_promote = True # move op

                    #run_ac('move -c @{} {} {} -L {}'.format(tmp_comment.name, old_path, path, self._ws_top), self._server)
                    defunct_list.remove(old_path)
                    keep_list.remove(path)
                    #logging.debug('removing "{}" from keep_list'.format(path))
                    os.remove(temp_move.name)
                else:
                    add_list.append(path)
                    keep_list.remove(path)
                    #logging.debug('removing "{}" from keep_list'.format(path))

        self.exec_op('defunct', defunct_list, tmp_comment.name)
        self.exec_op('add', add_list, tmp_comment.name)
        #logging.debug(keep_list)

        # make sure you undefunct the already 'defunct' files in the keep list
        # since the file is neither detected as move nor as an external file
        if keep_list:
            tmp_keep = tempfile.NamedTemporaryFile(delete=False)
            tmp_keep.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
            for elem in keep_list:
                tmp_keep.write('{}\n'.format(elem.strip()))
            tmp_keep.close()
            sparser = StatusParser(tmp_keep.name, self._ws_top, self._server, self._auth_opt)
            sparser.get_defunct_files()
            os.remove(tmp_keep.name)
            defunct_elems = sparser._elem_list
            if defunct_elems:
                tmp_undefunct = tempfile.NamedTemporaryFile(delete=False)
                tmp_undefunct.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
                for elem in defunct_elems:
                    path = elem[0]
                    path = path.encode('utf-8')
                    path = self.normalizePath(path)
                    tmp_undefunct.write('{}\n'.format(path.strip()))
                tmp_undefunct.close()
                run_ac_ignore_error('undefunct -c @{} -l {} -L {}'.format(tmp_comment.name, tmp_undefunct.name, self._ws_top), self._server, self._auth_opt)
                os.remove(tmp_undefunct.name)

        self.do_keeps(depot, keep_list, tmp_comment.name, commit_from_mark, merge_from_mark)
        os.remove(tmp_comment.name)
        return commit_sha

    def parse_export(self, depot):
        #
        first_commit_sha = ''
        commit_sha = ''
        dry_run = False
        first_commit_or_reset = True
        fail_this_push = False
        disallowed_local_branch = False
        called_incoming_changes = False
        err_msg = 'error not-supported'
        root = ''

        self.next()
        for line in self:
            #logging.debug('export: %s' % line)
            if self.check('feature'):
                pass
            elif self.check('blob'):
                self.parse_blob()
            elif self.check('commit') or self.check('reset'):
                # if push is not to remote master
                # then display error
                remote_branch = line.split('/')[-1].strip()
                if remote_branch != 'master':
                    disallowed_local_branch = True
                    dry_run = True
                    fail_this_push = True

                # one time initialization
                if first_commit_or_reset:
                    first_commit_or_reset = False
                    if not fail_this_push:
                        self.remove_all_members('push')
                        root = r'{}'.format(self.get_root())

                    # check if there are incoming changes
                    if not called_incoming_changes:
                        called_incoming_changes = True
                        if self.has_incoming_changes():
                            log_to_file('backing has changes not in local')
                            dry_run = True
                            fail_this_push = True
                            err_msg = 'error refs/heads/master fetch first'

                if self.check('commit'):
                    commit_sha = self.parse_commit(depot, root, dry_run)
                    if not first_commit_sha:
                        first_commit_sha = commit_sha
            elif self.check('from'):
                self.next() # LF
            elif self.check('done'):
                break
            else:
                sys.exit('Unrecognized command in export block: [%s]' % line)

            #
            if disallowed_local_branch:
                display_accurev_error(" cannot push to the remote branch {name},\n"
                                      " checkout the master branch,\n"
                                      " merge from {name}, then push again or\n"
                                      " push to the remote master branch\n".format(name=remote_branch))
                # displays both remote branch error and fetch first error
                # so exit, if it is remote branch error
                toGit('error not-supported')
                sys.exit(1)

            if fail_this_push:
                if err_msg:
                    toGit(err_msg)
                sys.exit(1)

        return first_commit_sha, commit_sha

    def has_incoming_changes(self):
        # Since update will ignore member files
        # run 'stat -o' to expose incoming changes
        # that are blocked by the member files
        if self.get_overlap_members():
            return True

        update_parser = UpdateParser(self._ws_top, self._reroot, self._server, auth_opt=self._auth_opt)
        update_parser.do_update_preview()
        return update_parser._has_incoming_changes

    def do_export(self):
        self._promote_comment = tempfile.NamedTemporaryFile(delete=False)
        # make the promote comment file as UTF-8 and add "@@Content-Encoding: utf-8"
        self._promote_comment.write(codecs.BOM_UTF8)
        self._promote_comment.write('@@Content-Encoding: utf-8\n')

        depot = self.get_depot()
        first_commit, last_commit = self.parse_export(depot)
        if not last_commit:
            # no-op push; nothing to do
            # print('ok refs/heads/master')
            print('')
            return

        # there may be prior kept files from the failed push
        # so always check if there are kept files and promote them
        # TODO: also need to check for (overlap) files in case changes
        # were promoted to backing since the last failed push or during
        # the in-progress push !!!
        # TODO: Also need to do that during a fetch as well !!!

        # [Performance Improvement] Replaced 'stat -k' with trigger_promote
        # out = run_ac('stat -k -L {}'.format(self._ws_top), self._server)
        if self._trigger_promote or last_commit:
            if self._push_option:
                issue = ''
                if self._push_option.startswith('cpk:'):
                    issue = self._push_option.replace('cpk:', '')
                if not issue:
                    toGit('error refs/heads/master invalid push option')
                    if not self._isCPKGuiDisabled:
                        display_accurev_error(suggestIssues(self._ws_top, self._server, self._auth_opt))
                    sys.exit(1)
            else:
                issue = get_git_config('accurev.{}.cpk'.format(self._alias), repo=self._repo)
            cpk = ''
            if len(issue.split()) >= 1:
                cpk = '-I "{}"'.format(issue)
                set_git_config('accurev.{}.cpk'.format(self._alias), '', repo=self._repo)
            # TODO promote using run_ac()
            server_opt = ' -H {} '.format(self._server) if self._server else ' '

            if(first_commit == last_commit):
                self._promote_comment.write('[git push] {}'.format(last_commit))
            else:
                self._promote_comment.write('[git push] {}..{}'.format(first_commit[0:7], last_commit[0:7]))
            self._promote_comment.close()

            cmdline = 'accurev promote{}{}-k -c @{} {} -L {}'.format(server_opt, self._auth_opt, self._promote_comment.name, cpk, self._ws_top)
            log_to_file('[cmd] {}'.format(cmdline))

            if sys.platform == 'win32':
                p = subprocess.Popen(cmdline, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
            else:
                import shlex
                p = subprocess.Popen(shlex.split(cmdline), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)

            with p.stdout:
                for line in iter(p.stdout.readline, b''):
                    #logging.debug('[promote]: {}'.format(line))
                    #logging.debug(line)
                    # TODO: Need to support Japanese version. (require changes)
                    if 'Please enter issue number ?' in line:

                        if self._isCPKGuiDisabled:
                            # if the repo is a proxy server's repo, the GUI is disabled and throw an error
                            p.kill()
                            toGit('error refs/heads/master no issue selected')
                            sys.exit(1)
                        else:
                            # interact with the user in the GUI
                            info = InfoParser(self._ws_top, self._server, self._auth_opt)
                            issue = get_cpk_issues(info._depot, info._ws_name, info._principal, self._server, self._auth_opt) #passing current user.
                            if issue:
                                p.stdin.write('{}\n'.format(issue))
                            else:
                                p.kill()
                                toGit('error refs/heads/master no issue selected')
                                #toGit('') # this tells git not to send the commits next time
                                # user did not select an issue, no need to suggest issues in this case
                                #display_accurev_error(suggestIssues(self._ws_top, self._server))
                                sys.exit(1)
                    elif line.startswith('Promoted element'):
                        elem_path = self.normalizePath(' '.join(line.split()[2:]))
                        if elem_path.startswith('/./'):
                            elem_path = elem_path[3:]
                        log_to_file('promoted {}'.format(elem_path))
                        full_path = r'{}'.format(os.path.join(r'{}'.format(self._ws_top.strip('"')), r'{}'.format(elem_path)))
                        # can only remove files, directories may not be empty at this time
                        if os.path.isfile(full_path):
                            os.remove(full_path)
            p.wait() # wait for the subprocess to exit
            os.remove(self._promote_comment.name)
            if p.returncode:
                err = p.stderr.read()
                if err.startswith("Issue not found.") or err.startswith("Issue does not match promote criteria."):
                    err = err.replace('\n', '').replace('\r', '')
                    if not self._isCPKGuiDisabled:
                        display_accurev_error(suggestIssues(self._ws_top, self._server, self._auth_opt))
                # make sure the err message does not contain a line feed
                # to avoid the commit mark being updated in the git marks file
                toGit('error refs/heads/master {}'.format(err.strip()))
                #toGit('') # this tells git not to send the commits next time
                #display_accurev_error(err)
                sys.exit(1)

        try:
            self._promote_comment.close()
            os.remove(self._promote_comment.name)
        except:
            log_to_file('Failed to remove file or file is already removed: {}'.format(self._promote_comment.name))
        # success
        toGit('ok refs/heads/master')
        toGit('')

    def get_tip_ref(self):
        return git_rev_parse('{}/heads/master'.format(self._prefix), repo=self._repo)
    
    def get_root(self):
        ws_name = get_git_config('accurev.{}.wsname'.format(self._alias), repo=self._repo)
        rules = RulesParser(stream=ws_name, server=self._server, auth_opt=self._auth_opt)
        root = rules._incl_location
        if root:
            root = root.replace('\\', '/')
            root = root.lstrip('/.')
            return root
        return ''

    def get_overlap_members(self):
        return run_ac('stat -o -fl -L {}'.format(self._ws_top), self._server, self._auth_opt)

    def remove_overlap_members(self):
        out = self.get_overlap_members()
        if out:
            temp = tempfile.NamedTemporaryFile(delete=False)
            for line in io.StringIO(out):
                temp.write('{}\n'.format(line.strip()))
            temp.close()
            run_ac('purge -c {} -l {} -L {}'.format('"[git fetch]: purging overlapped files"', temp.name, self._ws_top), self._server, self._auth_opt)
            os.remove(temp.name)

    def remove_all_members(self, op):
        status_parser = StatusParser('', self._ws_top, self._server, self._auth_opt)
        status_parser.get_purge_list()
        purge_list = status_parser._elem_list
        if purge_list:
            temp = tempfile.NamedTemporaryFile(delete=False)
            temp.write(codecs.BOM_UTF8)  # changes the file to UTF-8-BOM
            for elem in purge_list:
                path = elem[0].encode('utf-8')  # elem = (path, status)
                path = self.normalizePath(path)
                temp.write(path + '\n')
            temp.close()
            comment = '"[git {}]: cleaning out previous failed push"'.format(op)
            run_ac('purge -c {} -l {} -L {}'.format(comment, temp.name, self._ws_top), self._server, self._auth_opt)
            os.remove(temp.name)

    def clear_all_rules(self, ws_name):
        rules = RulesParser(ws_name, self._server, self._auth_opt)
        if rules._elements:
            temp = tempfile.NamedTemporaryFile(delete=False)
            for line in rules._elements:
                temp.write('{}\n'.format(line.strip()))
            temp.close()
            run_ac('clear -s "{}" -l {}'.format(ws_name, temp.name), self._server, self._auth_opt)
            os.remove(temp.name)

    # save the depot name in git config file for
    # faster access instead of calling parser.
    def get_depot(self):
        depot = get_git_config('accurev.{}.depot'.format(self._alias), self._repo)
        if not depot:
            stream_parser = StreamParser(self._stream, self._server, self._auth_opt)
            depot = stream_parser._depot
            set_git_config('accurev.{}.depot'.format(self._alias), depot, self._repo)
        return depot
    
    def get_ws_name(self):
        ws_name = get_git_config('accurev.{}.wsname'.format(self._alias), repo=self._repo)
        return ws_name

    def do_import(self):
        # this can be invoked for 'clone', 'fetch', 'pull', and 'remote update'
        cloning = False
        reuse_ws = False
        #logging.debug('do_import:\nself:\n{}'.format(self))
        depot = self.get_depot()
        if not os.path.exists(r'{}'.format(self._ws_top.strip('"'))):
            # the workspace directory does not exist yet
            # so as long as we don't issue commands that will populate files
            # we should still end up with an empty workspace
            ws_parser = WspaceParser(depot, self._ws_top, self._server, self._auth_opt)
            ws_name = ws_parser.get_unique_name(self._stream, self._alias)
            #logging.debug('ws_name: {}\nws_parser:\n{}'.format(ws_name, ws_parser))
            set_git_config('accurev.{}.wsname'.format(self._alias), ws_name, repo=self._repo)
            if ws_parser._reusable_ws:
                # now reuse the wspace
                log_to_file('Reuse {}wspace: {}'.format('hidden ' if ws_parser._reusable_ws_hidden else '', ws_parser._reusable_ws))
                make_sure_path_exists(r'{}'.format(self._ws_top.strip('"')))
                old_ws_name = ws_parser._reusable_ws
                if ws_parser._reusable_ws_hidden:
                    run_ac('reactivate wspace "{}"'.format(old_ws_name), self._server, self._auth_opt) # or the following won't work!

                run_ac('chws -w "{}" -b "{}" -e u -l {} {}'.format(old_ws_name, self._stream, self._ws_top, ws_name),
                       self._server, self._auth_opt)
                run_ac('update -9 -L {}'.format(self._ws_top), self._server, self._auth_opt)
                self.clear_all_rules(ws_name)
                self.remove_all_members('clone')
                if self._path:
                    run_ac('incldo -s "{}" /./'.format(ws_name), self._server, self._auth_opt)
                reuse_ws = True
            else:
                incl_opt = '-i ' if self._path else ''
                run_ac('mkws -w "{}" {}-b "{}" -e u -l {}'.format(ws_name, incl_opt, self._stream, self._ws_top), self._server, self._auth_opt)
            cloning = True

        # here is the reasoning, if a push failed previously leaving kept files
        # in the workspace, and those files have become overlap because there are
        # newer versions in the backing, update will still succeed because those
        # are members. The workspace then would be in an inconsistent  state
        # However, if we simply remove the overlapped members, then update will
        # pull down the newer versions, and git will initiate merges on them,
        # because they are committed in the first place, get it?
        #self.remove_overlap_members()
        # however, it's hard...
        if not cloning:
            # this does not apply for clone, either in a new or reused wspace
            self.remove_all_members('fetch')

        ref_head = ''
        ref = ''
        while self.check('import'):
            ref = self[1]
            if not cloning:
                ref_head = self.get_tip_ref()
                log_to_file('[import ref]: %s (%s)' % (ref, ref_head))
            self.next()

        toGit('feature done')
        if os.path.exists(self._git_marks):
            toGit('feature import-marks=%s' % self._git_marks.strip('"'))
        toGit('feature export-marks=%s' % self._git_marks.strip('"'))
        sys.stdout.flush()

        update_parser = UpdateParser(self._ws_top, self._reroot, self._server, auth_opt=self._auth_opt, show_progress=self._show_progress)
        if self._path and cloning:
            # this covers the new and the reused wspace
            update_parser.do_incl(self._path)
        elif cloning and reuse_ws:
            update_parser.do_pop(self._path)
        else:
            root = self.get_root()
            self._target_trans = get_git_config("accurev.trans.targettrans", repo=self._repo)
            if self._target_trans:
                update_parser.do_update_with_trans(root, self._target_trans)
                # set_git_config("accurev.trans.targettrans", '', repo=self._repo)
            else:
                update_parser.do_update(root)

        if not self._target_trans:
            # 'info' command in 7.0 and above contains the transaction information
            # use 'show wspaces' command to get the update trans to maintain
            # compatibility with older versions
            ws_name = get_git_config('accurev.{}.wsname'.format(self._alias), repo=self._repo)
            trans_parser = UpdateTransParser(self._server, self._auth_opt)
            update_trans = trans_parser.get_update_trans(ws_name)

        # to differentiate changes from the real user in 'git blame'
        principal = 'others'
        
        commit_mark = 1
        #logging.debug('update_parser:\n{}'.format(update_parser))
        if cloning or update_parser._elem_list:
            #self.write_commit(info, ref_head)
            commit_mark = update_parser._mark
            toGit('reset %s/heads/master' % self._prefix)
            toGit('commit %s/heads/master' % self._prefix)
            toGit('mark :{}'.format(commit_mark))

            if self._target_trans:
                trans = TransHistParser(self._target_trans, self.get_depot(), self._server, self._auth_opt)
                tz_offset = get_tz_offset()
                commit_time = int(trans.time)
                # ('author' (SP <name>)? SP LT <email> GT SP <when> LF)?
                # 'committer' (SP <name>)? SP LT <email> GT SP <when> LF
                toGit('author {} <{}> {} {}'.format(trans.user, '@accurev.com', commit_time, tz_offset))
                toGit('committer {} <{}> {} {}'.format(trans.user, '@accurev.com', commit_time, tz_offset))

                comments = 'import from accurev @ {}:{}\n[{}: {}]'.format(depot, self._target_trans, trans.type, trans.comment)
            else:
                tz_offset = get_tz_offset()
                commit_time = int(time.time())
                # ('author' (SP <name>)? SP LT <email> GT SP <when> LF)?
                # 'committer' (SP <name>)? SP LT <email> GT SP <when> LF
                toGit('author {} <{}> {} {}'.format(principal, '@.com', commit_time, tz_offset))
                toGit('committer {} <{}> {} {}'.format(principal, '@.com', commit_time, tz_offset))

                comments = 'import from accurev @ {}:{}'.format(depot, update_trans)

            toGit('data {}'.format(len(comments)))
            toGit(comments)
            if ref_head:
                toGit('from {}'.format(ref_head))

            for elem in update_parser._elem_list:
                #logging.debug(elem)
                toGit(elem)

        if update_parser._has_incoming_changes:
            toGit('')
            toGit('reset {}/heads/master'.format(self._prefix))
            toGit('from :{}'.format(commit_mark))
            toGit('')

        toGit('done')
        sys.stdout.flush()

        if cloning:
            # make the newly created workspace hidden to avoid user's meddling
            # can only remove the wspace after we have done an update
            run_ac('rmws "{}"'.format(ws_name), self._server, self._auth_opt)

        log_to_file('end of import')
    
    def run(self):
        # delete the tmp git_marks file from the last failed push before processing
        if os.path.exists(self._tmp_git_marks):
            log_to_file('deleting {} for export'.format(self._tmp_git_marks))
            os.remove(self._tmp_git_marks)

        for line in self:
            if self.check('capabilities'):
                toGit('import')
                toGit('export')
                toGit('refspec refs/heads/*:%s/heads/*' % self._prefix)

                if os.path.exists(self._git_marks):
                    toGit('*import-marks %s' % self._git_marks)

                toGit('*export-marks %s' % self._git_marks)
                toGit('option')
                toGit('')
            elif self.check('list'):
                toGit('? refs/heads/master')
                toGit('@refs/heads/master HEAD')
                toGit('')
            elif self.check('import'):
                self.do_import()
                
            elif self.check('export'):
                self.do_export()
            elif self.check('option progress'):
                self._show_progress = ('true' in line)
                toGit('ok')
            elif self.check('option push-option'):
                self._push_option = line.replace('option push-option ', '').strip('"').lower()
                log_to_file('[Push Option]: {}'.format(self._push_option))
                toGit('ok')
            elif self.check('option'):
                toGit('unsupported')
            elif line == '':
                break
            else:
                sys.exit('Unhandled command in main loop: [%s]' % line)
                
            sys.stdout.flush()
    
def main():
    if len(sys.argv) == 1:
        print(GIT_CLIENT_VERSION)
        return
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)

    init_logging()

    alias = sys.argv[1]
    url = sys.argv[2]
    
    parser = RemoteParser(alias, url)
    parser.run()
    
if __name__ == '__main__':
    main()
