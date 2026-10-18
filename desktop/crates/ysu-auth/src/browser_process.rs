//! Windows child creation atomically bound to a private kill-on-close Job Object.
use std::{
    ffi::OsStr,
    fs::OpenOptions,
    io,
    mem::size_of,
    os::windows::{
        ffi::OsStrExt,
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
    },
    path::Path,
    ptr,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::{SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, WAIT_OBJECT_0, WAIT_TIMEOUT},
    System::{
        JobObjects::{
            CreateJobObjectW, JobObjectBasicAccountingInformation,
            JobObjectExtendedLimitInformation, QueryInformationJobObject, SetInformationJobObject,
            TerminateJobObject, JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        Pipes::CreatePipe,
        Threading::{
            CreateProcessW, DeleteProcThreadAttributeList, GetExitCodeProcess,
            InitializeProcThreadAttributeList, UpdateProcThreadAttribute, WaitForSingleObject,
            CREATE_NO_WINDOW, EXTENDED_STARTUPINFO_PRESENT, LPPROC_THREAD_ATTRIBUTE_LIST,
            PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, PROC_THREAD_ATTRIBUTE_JOB_LIST,
            STARTF_USESTDHANDLES, STARTUPINFOEXW,
        },
    },
};

struct Attributes {
    pointer: LPPROC_THREAD_ATTRIBUTE_LIST,
    _storage: Vec<usize>,
}
impl Attributes {
    fn new() -> io::Result<Self> {
        let mut bytes = 0;
        unsafe {
            InitializeProcThreadAttributeList(ptr::null_mut(), 2, 0, &mut bytes);
        }
        if bytes == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut storage = vec![0usize; bytes.div_ceil(size_of::<usize>())];
        let pointer = storage.as_mut_ptr().cast();
        if unsafe { InitializeProcThreadAttributeList(pointer, 2, 0, &mut bytes) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            pointer,
            _storage: storage,
        })
    }
    fn add(&self, key: u32, value: &[HANDLE]) -> io::Result<()> {
        let ok = unsafe {
            UpdateProcThreadAttribute(
                self.pointer,
                0,
                key as usize,
                value.as_ptr().cast(),
                std::mem::size_of_val(value),
                ptr::null_mut(),
                ptr::null(),
            )
        };
        if ok == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
}
impl Drop for Attributes {
    fn drop(&mut self) {
        unsafe {
            DeleteProcThreadAttributeList(self.pointer);
        }
    }
}

fn quote(out: &mut Vec<u16>, arg: &OsStr) -> io::Result<()> {
    out.push(b'"' as u16);
    let mut slashes = 0;
    for c in arg.encode_wide() {
        if c == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "NUL in argument",
            ));
        }
        if c == b'\\' as u16 {
            slashes += 1;
            continue;
        }
        let count = if c == b'"' as u16 {
            slashes * 2 + 1
        } else {
            slashes
        };
        out.extend(std::iter::repeat_n(b'\\' as u16, count));
        out.push(c);
        slashes = 0;
    }
    out.extend(std::iter::repeat_n(b'\\' as u16, slashes * 2));
    out.push(b'"' as u16);
    Ok(())
}

/// Anonymous, non-inheritable pipe as (read, write). `Child::spawn` marks only the
/// child's ends inheritable and its handle list hands exactly those to Chromium.
pub(crate) fn pipe() -> io::Result<(OwnedHandle, OwnedHandle)> {
    let (mut read, mut write) = (ptr::null_mut(), ptr::null_mut());
    if unsafe { CreatePipe(&mut read, &mut write, ptr::null(), 0) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe {
        (
            OwnedHandle::from_raw_handle(read),
            OwnedHandle::from_raw_handle(write),
        )
    })
}

pub(crate) struct Child {
    process: OwnedHandle,
    job: OwnedHandle,
    pid: u32,
}
impl Child {
    /// `inherit` lists the only extra handles the child receives besides NUL stdio.
    pub fn spawn(executable: &Path, args: &[&OsStr], inherit: &[HANDLE]) -> io::Result<Self> {
        let mut application: Vec<u16> = executable.as_os_str().encode_wide().collect();
        if application.contains(&0) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "NUL in path"));
        }
        application.push(0);
        let mut line = Vec::new();
        quote(&mut line, executable.as_os_str())?;
        for arg in args {
            line.push(b' ' as u16);
            quote(&mut line, arg)?;
        }
        line.push(0);
        if line.len() > 32767 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "command line too long",
            ));
        }
        let raw_job = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
        if raw_job.is_null() {
            return Err(io::Error::last_os_error());
        }
        let job = unsafe { OwnedHandle::from_raw_handle(raw_job) };
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if unsafe {
            SetInformationJobObject(
                raw_job,
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let nul = OpenOptions::new().read(true).write(true).open("NUL")?;
        let raw_nul = nul.as_raw_handle();
        if unsafe { SetHandleInformation(raw_nul, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT) } == 0 {
            return Err(io::Error::last_os_error());
        }
        for handle in inherit {
            if unsafe { SetHandleInformation(*handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT) }
                == 0
            {
                return Err(io::Error::last_os_error());
            }
        }
        let attributes = Attributes::new()?;
        let jobs = [raw_job];
        let inherited: Vec<HANDLE> = std::iter::once(raw_nul)
            .chain(inherit.iter().copied())
            .collect();
        attributes.add(PROC_THREAD_ATTRIBUTE_JOB_LIST, &jobs)?;
        attributes.add(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &inherited)?;
        let mut startup = STARTUPINFOEXW::default();
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = raw_nul;
        startup.StartupInfo.hStdOutput = raw_nul;
        startup.StartupInfo.hStdError = raw_nul;
        startup.lpAttributeList = attributes.pointer;
        let mut process_info = PROCESS_INFORMATION::default();
        // JOB_LIST binds the child before its first instruction; no post-spawn assignment race.
        let ok = unsafe {
            CreateProcessW(
                application.as_ptr(),
                line.as_mut_ptr(),
                ptr::null(),
                ptr::null(),
                1,
                EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW,
                ptr::null(),
                ptr::null(),
                &startup.StartupInfo,
                &mut process_info,
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        let process = unsafe { OwnedHandle::from_raw_handle(process_info.hProcess) };
        let thread = unsafe { OwnedHandle::from_raw_handle(process_info.hThread) };
        drop(thread);
        Ok(Self {
            process,
            job,
            pid: process_info.dwProcessId,
        })
    }
    pub fn id(&self) -> u32 {
        self.pid
    }
    fn exit_code(&self) -> io::Result<u32> {
        let mut code = 0;
        if unsafe { GetExitCodeProcess(self.process.as_raw_handle(), &mut code) } == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(code)
        }
    }
    pub fn try_wait(&mut self) -> io::Result<Option<u32>> {
        match unsafe { WaitForSingleObject(self.process.as_raw_handle(), 0) } {
            WAIT_OBJECT_0 => self.exit_code().map(Some),
            WAIT_TIMEOUT => Ok(None),
            _ => Err(io::Error::last_os_error()),
        }
    }
    pub fn kill(&mut self) -> io::Result<()> {
        if unsafe { TerminateJobObject(self.job.as_raw_handle(), 1) } == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    pub fn wait(&mut self) -> io::Result<u32> {
        let end = Instant::now() + Duration::from_secs(3);
        loop {
            let mut info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
            if unsafe {
                QueryInformationJobObject(
                    self.job.as_raw_handle(),
                    JobObjectBasicAccountingInformation,
                    (&mut info as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                    size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    ptr::null_mut(),
                )
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
            if info.ActiveProcesses == 0 && self.try_wait()?.is_some() {
                return self.exit_code();
            }
            if Instant::now() >= end {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "browser job cleanup timed out",
                ));
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}
impl Drop for Child {
    fn drop(&mut self) {
        let _ = self.kill();
    }
}
