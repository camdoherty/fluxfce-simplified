todo
investigate running enable logic periodically if state is enabled? explore this

[Systemd Units]
  Scheduler Timer (fluxfce-scheduler.timer): Enabled, Active (waiting)
  Scheduler Service (fluxfce-scheduler.service): Disabled, Inactive  ## this needs to be enabled
  Login Service (fluxfce-login.service): Enabled, Inactive
  (For detailed logs/status, use 'systemctl --user status ...' or 'journalctl --user -u ...')
-------------------------
cad@mintpad:~$ fluxfce enable
Enabling scheduling...
Automatic theme scheduling enabled.
cad@mintpad:~$ fluxfce status
Getting status...
--- fluxfce Status ---

[Configuration]
  Location:      43.65N, 79.38W
  Timezone:      America/Toronto
  Light Theme:   Adwaita
  Dark Theme:    Adwaita-dark

[State]
  Last Auto-Applied: day

[Calculated Sun Times (Today)]
  Sunrise:       2025-05-05 06:04:30-04:00
  Sunset:        2025-05-05 20:23:27-04:00
  Current Period:  Night

[Scheduled Transitions ('at' jobs)]
  Status:        Enabled (2 job(s) found)
  - Job 21: Day at Tue May  6 06:03:00 2025
  - Job 22: Night at Tue May  6 20:24:00 2025

[Systemd Units]
  Scheduler Timer (fluxfce-scheduler.timer): Enabled, Active (waiting)
  Scheduler Service (fluxfce-scheduler.service): Disabled, Inactive
  Login Service (fluxfce-login.service): Enabled, Inactive
  (For detailed logs/status, use 'systemctl --user status ...' or 'journalctl --user -u ...')
-------------------------


