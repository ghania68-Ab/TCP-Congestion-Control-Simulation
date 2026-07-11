#!/usr/bin/env python3
"""
TCP Congestion Control Simulation: Tahoe vs Reno
==================================================
Simulates TCP Tahoe and TCP Reno congestion control algorithms
over a simple wired network topology with a bottleneck link, using
Mininet for topology definition.

Topology (defined via Mininet Topo class):
    Sender ----[10 Mbps, 5ms]----> Router ----[1.5 Mbps, 20ms]----> Receiver
                                                        |
                                                   Bottleneck Link

The bottleneck link (Router -> Receiver) has lower bandwidth (1.5 Mbps) and
higher latency (20ms), causing queue buildup and packet drops when the sender's
congestion window exceeds the available capacity.

This simulation uses a discrete-event approach where each time step represents
an ACK event. The congestion window determines how many unACKed packets can be
in flight, and loss events are triggered probabilistically when cwnd exceeds
the network's bandwidth-delay product.

Both 3-duplicate-ACK (Fast Retransmit / Fast Recovery) and RTO timeout
loss detection paths are implemented, following RFC 2581 (Tahoe/Reno
congestion avoidance) and RFC 6298 (RTO calculation).
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import random
import json
import csv
import os

# =============================================================================
# Mininet Topology Definition
# =============================================================================
_MININET_AVAILABLE = False
try:
    from mininet.topo import Topo as _MininetTopo
    from mininet.link import TCLink as _TCLink
    _MININET_AVAILABLE = True
except ImportError:
    print("[INFO] Mininet not found — using built-in topology fallback.")
    print("[INFO] On Linux, install Mininet for full topology support:")
    print("       sudo apt install python3-mininet")


if _MININET_AVAILABLE:
    # Full Mininet Topo class with TCLink bandwidth/delay config
    class TCPBottleneckTopo(_MininetTopo):
        """
        Bottleneck network topology defined using Mininet's Topo API.

        Layout:
            sender ---[10 Mbps, 5 ms]--- router ---[1.5 Mbps, 20 ms]--- receiver

        The Router-to-Receiver link is the bottleneck (lower bandwidth,
        higher delay).  Link parameters are stored as class attributes so
        the discrete-event simulation can read them directly.
        """

        SENDER_ROUTER_BW_Mbps = 10
        SENDER_ROUTER_DELAY_MS = 5
        ROUTER_RECEIVER_BW_Mbps = 1.5
        ROUTER_RECEIVER_DELAY_MS = 20
        PACKET_SIZE_BYTES = 1500
        ROUTER_QUEUE_PKTS = 20

        def build(self):
            sender = self.addHost('sender')
            receiver = self.addHost('receiver')
            router = self.addSwitch('router')
            self.addLink(
                sender, router, cls=_TCLink,
                bw=self.SENDER_ROUTER_BW_Mbps,
                delay=f'{self.SENDER_ROUTER_DELAY_MS}ms',
            )
            self.addLink(
                router, receiver, cls=_TCLink,
                bw=self.ROUTER_RECEIVER_BW_Mbps,
                delay=f'{self.ROUTER_RECEIVER_DELAY_MS}ms',
            )
            return sender, router, receiver
else:
    # Fallback topology class (mirrors Mininet Topo API, works on any OS)
    class TCPBottleneckTopo:
        """
        Bottleneck network topology (Mininet-compatible fallback).

        When Mininet is not installed (e.g. on Windows), this class provides
        the same topology definition and link parameters.  On Linux with
        Mininet installed, the full Mininet Topo subclass is used instead.

        Layout:
            sender ---[10 Mbps, 5 ms]--- router ---[1.5 Mbps, 20 ms]--- receiver
        """

        SENDER_ROUTER_BW_Mbps = 10
        SENDER_ROUTER_DELAY_MS = 5
        ROUTER_RECEIVER_BW_Mbps = 1.5
        ROUTER_RECEIVER_DELAY_MS = 20
        PACKET_SIZE_BYTES = 1500
        ROUTER_QUEUE_PKTS = 20

        def __init__(self):
            self._hosts = []
            self._switches = []
            self._links = []

        def addHost(self, name):
            self._hosts.append(name)
            return name

        def addSwitch(self, name):
            self._switches.append(name)
            return name

        def addLink(self, node1, node2, **kwargs):
            self._links.append((node1, node2, kwargs))
            return (node1, node2)

        def build(self):
            sender = self.addHost('sender')
            receiver = self.addHost('receiver')
            router = self.addSwitch('router')
            self.addLink(sender, router, bw=self.SENDER_ROUTER_BW_Mbps,
                         delay=f'{self.SENDER_ROUTER_DELAY_MS}ms')
            self.addLink(router, receiver, bw=self.ROUTER_RECEIVER_BW_Mbps,
                         delay=f'{self.ROUTER_RECEIVER_DELAY_MS}ms')
            return sender, router, receiver


# Build the topology once — parameters below are derived from it
_topo = TCPBottleneckTopo()

# =============================================================================
# Network Parameters (sourced from Mininet topology)
# =============================================================================
SENDER_TO_ROUTER_BW = _topo.SENDER_ROUTER_BW_Mbps * 1e6      # 10 Mbps
ROUTER_TO_RECEIVER_BW = _topo.ROUTER_RECEIVER_BW_Mbps * 1e6   # 1.5 Mbps
SENDER_TO_ROUTER_DELAY = _topo.SENDER_ROUTER_DELAY_MS / 1000  # 0.005 s
ROUTER_TO_RECEIVER_DELAY = _topo.ROUTER_RECEIVER_DELAY_MS / 1000  # 0.02 s
PACKET_SIZE = _topo.PACKET_SIZE_BYTES                         # 1500 bytes
ROUTER_QUEUE_SIZE = _topo.ROUTER_QUEUE_PKTS                   # 20 packets

# Derived constants
ONE_WAY_DELAY = SENDER_TO_ROUTER_DELAY + ROUTER_TO_RECEIVER_DELAY
BASE_RTT = 2 * ONE_WAY_DELAY  # 50 ms
BOTTLENECK_BDP = max(int(ROUTER_TO_RECEIVER_BW * BASE_RTT / (PACKET_SIZE * 8)), 1)

# Simulation control
TOTAL_ACK_EVENTS = 6000
INITIAL_CWND = 1.0
INITIAL_SSTHRESH = 64.0
# Loss begins when cwnd exceeds BDP + router queue capacity (queue overflow)
LOSS_THRESHOLD_CWND = BOTTLENECK_BDP + ROUTER_QUEUE_SIZE  # 6 + 20 = 26 packets
BASE_LOSS_PROB = 0.04
MIN_RTO = 0.2  # Minimum RTO in seconds (per RFC 6298)
SEED = 42

# =============================================================================
# Font Configuration (cross-platform)
# =============================================================================
import platform
_os = platform.system()
if _os == 'Linux':
    _dejavu = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    if os.path.isfile(_dejavu):
        fm.fontManager.addfont(_dejavu)
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# =============================================================================
# TCP Tahoe
# =============================================================================
def simulate_tahoe(seed=SEED):
    """
    Simulate TCP Tahoe congestion control.

    Tahoe behavior:
    - Slow Start: cwnd += 1 per ACK (exponential growth) while cwnd < ssthresh
    - Congestion Avoidance: cwnd += 1/cwnd per ACK (linear) while cwnd >= ssthresh
    - On 3 duplicate ACKs: ssthresh = cwnd/2, cwnd = 1 (reset to slow start)
    - On RTO timeout:      ssthresh = cwnd/2, cwnd = 1 (reset to slow start)
    """
    rng = random.Random(seed)

    cwnd = INITIAL_CWND
    ssthresh = INITIAL_SSTHRESH
    dup_ack_count = 0
    total_dropped = 0
    total_acked = 0
    timeout_count = 0

    time_log, cwnd_log, rtt_log, drop_log, throughput_log = [], [], [], [], []
    bytes_sent = 0.0
    current_time = 0.0
    srtt = BASE_RTT
    rttvar = BASE_RTT / 2
    last_new_ack_time = 0.0

    for ack_event in range(TOTAL_ACK_EVENTS):
        # --- RTO Timeout check (per RFC 6298) ---
        # Fires when no new ACK has been received for RTO duration.
        # RTO = SRTT + 4 * RTTVAR, with a floor of MIN_RTO.
        if current_time > BASE_RTT:
            rto = srtt + 4.0 * rttvar
            rto = max(rto, MIN_RTO)
            if current_time - last_new_ack_time > rto:
                # Timeout: same response as 3-dup-ACK for Tahoe
                ssthresh = max(cwnd / 2.0, 2.0)
                cwnd = 1.0
                dup_ack_count = 0
                last_new_ack_time = current_time  # restart timer
                timeout_count += 1

        # --- Determine if this ACK is a duplicate or new ---
        if cwnd > LOSS_THRESHOLD_CWND:
            excess = (cwnd - LOSS_THRESHOLD_CWND) / LOSS_THRESHOLD_CWND
            loss_prob = BASE_LOSS_PROB * (1 + 2.0 * excess)
        else:
            loss_prob = 0.0

        is_loss = rng.random() < loss_prob

        if is_loss:
            dup_ack_count += 1
            total_dropped += 1

            if dup_ack_count == 3:
                # Tahoe: triple-dup-ACK -> ssthresh = cwnd/2, cwnd = 1
                ssthresh = max(cwnd / 2.0, 2.0)
                cwnd = 1.0
                dup_ack_count = 0
                last_new_ack_time = current_time  # restart timer after retransmit
        else:
            # New ACK received — decay dup counter
            dup_ack_count = max(0, dup_ack_count - 1)
            total_acked += 1
            bytes_sent += PACKET_SIZE
            last_new_ack_time = current_time  # new ACK restarts timer

            # Congestion window update
            if cwnd < ssthresh:
                cwnd += 1.0  # Slow Start: exponential
            else:
                cwnd += 1.0 / cwnd  # Congestion Avoidance: linear

        # --- Calculate RTT ---
        queue_depth = max(0, cwnd - BOTTLENECK_BDP)
        queuing_delay = (queue_depth * PACKET_SIZE * 8 / ROUTER_TO_RECEIVER_BW)
        queuing_delay = min(queuing_delay, 0.4)
        jitter = rng.gauss(0, 0.003)
        measured_rtt = BASE_RTT + queuing_delay + jitter
        measured_rtt = max(measured_rtt, BASE_RTT)

        # Jacobson/Karels RTT estimation
        alpha = 0.125
        beta = 0.25
        rttvar = (1 - beta) * rttvar + beta * abs(srtt - measured_rtt)
        srtt = (1 - alpha) * srtt + alpha * measured_rtt

        # Time advancement: each ACK represents a fraction of an RTT
        min_spacing = (PACKET_SIZE * 8) / ROUTER_TO_RECEIVER_BW
        ack_spacing = max(srtt / max(cwnd, 1), min_spacing)
        current_time += ack_spacing

        # --- Log metrics ---
        time_log.append(current_time)
        cwnd_log.append(cwnd)
        rtt_log.append(measured_rtt * 1000)  # ms
        drop_rate = total_dropped / max(total_dropped + total_acked, 1)
        drop_log.append(drop_rate * 100)  # percent
        throughput_kbps = (bytes_sent * 8) / (current_time * 1000) if current_time > 0 else 0
        throughput_log.append(throughput_kbps)

    return {
        'time': time_log, 'cwnd': cwnd_log, 'rtt': rtt_log,
        'drop_rate': drop_log, 'throughput': throughput_log,
        'total_dropped': total_dropped, 'total_sent': total_dropped + total_acked,
        'total_acked': total_acked, 'bytes_transmitted': bytes_sent,
        'timeouts': timeout_count,
    }


# =============================================================================
# TCP Reno
# =============================================================================
def simulate_reno(seed=SEED):
    """
    Simulate TCP Reno congestion control.

    Reno behavior (same growth as Tahoe, DIFFERENT loss response):
    - Slow Start: cwnd += 1 per ACK while cwnd < ssthresh
    - Congestion Avoidance: cwnd += 1/cwnd per ACK while cwnd >= ssthresh
    - On 3 duplicate ACKs: ssthresh = cwnd/2, cwnd = ssthresh + 3 (fast recovery)
      - During fast recovery: cwnd += 1 per additional dup ACK
      - On new ACK exiting recovery: cwnd = ssthresh (enter congestion avoidance)
    - On RTO timeout: ssthresh = cwnd/2, cwnd = 1 (fall back to Tahoe behavior)
    """
    rng = random.Random(seed + 1000)

    cwnd = INITIAL_CWND
    ssthresh = INITIAL_SSTHRESH
    dup_ack_count = 0
    in_fast_recovery = False
    total_dropped = 0
    total_acked = 0
    timeout_count = 0

    time_log, cwnd_log, rtt_log, drop_log, throughput_log = [], [], [], [], []
    bytes_sent = 0.0
    current_time = 0.0
    srtt = BASE_RTT
    rttvar = BASE_RTT / 2
    last_new_ack_time = 0.0

    for ack_event in range(TOTAL_ACK_EVENTS):
        # --- RTO Timeout check (per RFC 6298) ---
        # Timeout cancels any ongoing Fast Recovery and resets to Slow Start.
        if current_time > BASE_RTT:
            rto = srtt + 4.0 * rttvar
            rto = max(rto, MIN_RTO)
            if current_time - last_new_ack_time > rto:
                ssthresh = max(cwnd / 2.0, 2.0)
                cwnd = 1.0
                dup_ack_count = 0
                in_fast_recovery = False  # cancel fast recovery
                last_new_ack_time = current_time
                timeout_count += 1

        # --- Loss probability (same model as Tahoe for fair comparison) ---
        if cwnd > LOSS_THRESHOLD_CWND:
            excess = (cwnd - LOSS_THRESHOLD_CWND) / LOSS_THRESHOLD_CWND
            loss_prob = BASE_LOSS_PROB * (1 + 2.0 * excess)
        else:
            loss_prob = 0.0

        is_loss = rng.random() < loss_prob

        if in_fast_recovery:
            if is_loss:
                # Dup ACK during fast recovery: inflate window
                cwnd += 1
                dup_ack_count += 1
                total_dropped += 1
            else:
                # New ACK: exit fast recovery -> congestion avoidance
                cwnd = ssthresh
                in_fast_recovery = False
                dup_ack_count = 0
                total_acked += 1
                bytes_sent += PACKET_SIZE
                last_new_ack_time = current_time  # new ACK restarts timer
                if cwnd >= ssthresh:
                    cwnd += 1.0 / cwnd
        else:
            if is_loss:
                dup_ack_count += 1
                total_dropped += 1

                if dup_ack_count == 3:
                    # Reno: triple-dup-ACK -> fast recovery
                    ssthresh = max(cwnd / 2.0, 2.0)
                    cwnd = ssthresh + 3.0
                    in_fast_recovery = True
                    dup_ack_count = 0
                    last_new_ack_time = current_time  # restart timer
            else:
                # Decay dup counter
                dup_ack_count = max(0, dup_ack_count - 1)
                total_acked += 1
                bytes_sent += PACKET_SIZE
                last_new_ack_time = current_time  # new ACK restarts timer

                # Congestion window update
                if cwnd < ssthresh:
                    cwnd += 1.0
                else:
                    cwnd += 1.0 / cwnd

        # --- Calculate RTT (same model) ---
        queue_depth = max(0, cwnd - BOTTLENECK_BDP)
        queuing_delay = (queue_depth * PACKET_SIZE * 8 / ROUTER_TO_RECEIVER_BW)
        queuing_delay = min(queuing_delay, 0.4)
        jitter = rng.gauss(0, 0.003)
        measured_rtt = BASE_RTT + queuing_delay + jitter
        measured_rtt = max(measured_rtt, BASE_RTT)

        alpha = 0.125
        beta = 0.25
        rttvar = (1 - beta) * rttvar + beta * abs(srtt - measured_rtt)
        srtt = (1 - alpha) * srtt + alpha * measured_rtt

        min_spacing = (PACKET_SIZE * 8) / ROUTER_TO_RECEIVER_BW
        ack_spacing = max(srtt / max(cwnd, 1), min_spacing)
        current_time += ack_spacing

        # Log
        time_log.append(current_time)
        cwnd_log.append(cwnd)
        rtt_log.append(measured_rtt * 1000)
        drop_rate = total_dropped / max(total_dropped + total_acked, 1)
        drop_log.append(drop_rate * 100)
        throughput_kbps = (bytes_sent * 8) / (current_time * 1000) if current_time > 0 else 0
        throughput_log.append(throughput_kbps)

    return {
        'time': time_log, 'cwnd': cwnd_log, 'rtt': rtt_log,
        'drop_rate': drop_log, 'throughput': throughput_log,
        'total_dropped': total_dropped, 'total_sent': total_dropped + total_acked,
        'total_acked': total_acked, 'bytes_transmitted': bytes_sent,
        'timeouts': timeout_count,
    }


# =============================================================================
# Run Multiple Simulations and Average
# =============================================================================
def run_multi_sim(sim_func, num_runs=5, seed_base=42):
    """Run multiple simulation instances and average results for stability."""
    all_results = []
    for i in range(num_runs):
        result = sim_func(seed=seed_base + i * 37)
        all_results.append(result)

    # Align to minimum length
    min_len = min(len(r['time']) for r in all_results)
    averaged = {key: [] for key in all_results[0].keys()}

    for j in range(min_len):
        for key in ['cwnd', 'rtt', 'drop_rate', 'throughput']:
            vals = [r[key][j] for r in all_results]
            averaged[key].append(np.mean(vals))
        averaged['time'].append(all_results[0]['time'][j])

    for key in ['total_dropped', 'total_sent', 'total_acked', 'bytes_transmitted', 'timeouts']:
        averaged[key] = sum(r[key] for r in all_results)

    return averaged


# =============================================================================
# Graph Generation
# =============================================================================
def generate_graphs(tahoe_single, reno_single, tahoe_avg, reno_avg, output_dir):
    """Generate all comparison graphs with clean, publication-quality layout.

    cwnd and RTT plots use single-run data to preserve sharp sawtooth patterns
    (multi-run averaging smears Tahoe's cwnd=1 resets into shallow dips).
    Drop rate and throughput plots use 5-run averaged data for stability.
    """
    print("\nGenerating comparison graphs...")

    # ---- Shared style constants ----
    TAHOE_COLOR = '#1565C0'
    RENO_COLOR  = '#C62828'
    REF_COLOR   = '#9E9E9E'
    BG_COLOR    = '#FAFAFA'
    GRID_COLOR  = '#E0E0E0'
    LABEL_SIZE  = 11
    TITLE_SIZE  = 13
    TICK_SIZE   = 9

    bottleneck_kbps = ROUTER_TO_RECEIVER_BW / 1000

    def _style_ax(ax, xlabel, ylabel, title):
        ax.set_facecolor(BG_COLOR)
        ax.set_xlabel(xlabel, fontsize=LABEL_SIZE, labelpad=8)
        ax.set_ylabel(ylabel, fontsize=LABEL_SIZE, labelpad=8)
        ax.set_title(title, fontsize=TITLE_SIZE, fontweight='bold', pad=12)
        ax.tick_params(labelsize=TICK_SIZE)
        ax.grid(True, color=GRID_COLOR, linewidth=0.6)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#BDBDBD')
        ax.spines['bottom'].set_color('#BDBDBD')

    def _clean_legend(ax, loc='upper right'):
        leg = ax.legend(loc=loc, fontsize=9, frameon=True,
                        fancybox=True, framealpha=0.92,
                        edgecolor='#CCCCCC', borderpad=0.8,
                        handlelength=2.2, handletextpad=0.6)
        leg.get_frame().set_linewidth(0.6)
        return leg

    # =================================================================
    # Graph 1: Congestion Window (single run)
    # =================================================================
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor('white')

    ax.plot(tahoe_single['time'], tahoe_single['cwnd'],
            color=TAHOE_COLOR, linewidth=1.3, label='TCP Tahoe', zorder=3)
    ax.plot(reno_single['time'], reno_single['cwnd'],
            color=RENO_COLOR, linewidth=1.3, label='TCP Reno', zorder=3)

    ax.axhline(y=BOTTLENECK_BDP, color=REF_COLOR, linestyle='--',
               linewidth=1.0, alpha=0.7, zorder=1)
    ax.text(0.98, 0.05, f'BDP = {BOTTLENECK_BDP} pkts', transform=ax.transAxes,
            fontsize=8.5, color='#757575', ha='right', va='bottom', style='italic')

    _style_ax(ax, 'Time (seconds)', 'Congestion Window (packets)',
              'Congestion Window: TCP Tahoe vs Reno')
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    _clean_legend(ax, loc='upper left')
    plt.tight_layout(pad=1.5)
    plt.savefig(os.path.join(output_dir, 'cwnd_comparison.png'), dpi=200,
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("  Saved: cwnd_comparison.png")

    # =================================================================
    # Graph 2: RTT (single run)
    # =================================================================
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor('white')

    ax.plot(tahoe_single['time'], tahoe_single['rtt'],
            color=TAHOE_COLOR, linewidth=1.2, label='TCP Tahoe', zorder=3)
    ax.plot(reno_single['time'], reno_single['rtt'],
            color=RENO_COLOR, linewidth=1.2, label='TCP Reno', zorder=3)

    ax.axhline(y=BASE_RTT * 1000, color=REF_COLOR, linestyle='--',
               linewidth=1.0, alpha=0.7, zorder=1)
    ax.text(0.98, 0.05, f'Base RTT = {BASE_RTT*1000:.0f} ms',
            transform=ax.transAxes,
            fontsize=8.5, color='#757575', ha='right', va='bottom', style='italic')

    _style_ax(ax, 'Time (seconds)', 'Round-Trip Time (ms)',
              'Round-Trip Time Variations: TCP Tahoe vs Reno')
    ax.set_xlim(left=0)
    _clean_legend(ax, loc='upper left')
    plt.tight_layout(pad=1.5)
    plt.savefig(os.path.join(output_dir, 'rtt_comparison.png'), dpi=200,
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("  Saved: rtt_comparison.png")

    # =================================================================
    # Graph 3: Drop Rate (5-run average)
    # =================================================================
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor('white')

    ax.plot(tahoe_avg['time'], tahoe_avg['drop_rate'],
            color=TAHOE_COLOR, linewidth=1.4, label='TCP Tahoe', zorder=3)
    ax.plot(reno_avg['time'], reno_avg['drop_rate'],
            color=RENO_COLOR, linewidth=1.4, label='TCP Reno', zorder=3)

    _style_ax(ax, 'Time (seconds)', 'Packet Drop Rate (%)',
              'Packet Drop Rate: TCP Tahoe vs Reno')
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    _clean_legend(ax, loc='upper left')
    plt.tight_layout(pad=1.5)
    plt.savefig(os.path.join(output_dir, 'drop_rate_comparison.png'), dpi=200,
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("  Saved: drop_rate_comparison.png")

    # =================================================================
    # Graph 4: Throughput (5-run average)
    # =================================================================
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor('white')

    ax.plot(tahoe_avg['time'], tahoe_avg['throughput'],
            color=TAHOE_COLOR, linewidth=1.4, label='TCP Tahoe', zorder=3)
    ax.plot(reno_avg['time'], reno_avg['throughput'],
            color=RENO_COLOR, linewidth=1.4, label='TCP Reno', zorder=3)

    ax.axhline(y=bottleneck_kbps, color=REF_COLOR, linestyle='--',
               linewidth=1.0, alpha=0.7, zorder=1)
    ax.text(0.98, 0.05, f'Bottleneck = {bottleneck_kbps:.0f} kbps',
            transform=ax.transAxes,
            fontsize=8.5, color='#757575', ha='right', va='bottom', style='italic')

    _style_ax(ax, 'Time (seconds)', 'Throughput (kbps)',
              'Throughput Over Time: TCP Tahoe vs Reno')
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    _clean_legend(ax, loc='upper left')
    plt.tight_layout(pad=1.5)
    plt.savefig(os.path.join(output_dir, 'throughput_comparison.png'), dpi=200,
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("  Saved: throughput_comparison.png")

    # =================================================================
    # Graph 5: Summary Dashboard (2x2)
    # =================================================================
    fig, axes = plt.subplots(2, 2, figsize=(13, 9.5))
    fig.patch.set_facecolor('white')
    fig.suptitle('TCP Tahoe vs Reno: Performance Dashboard',
                 fontsize=15, fontweight='bold', y=0.98)

    # (a) cwnd — single run for sharp sawtooth
    ax = axes[0, 0]
    ax.plot(tahoe_single['time'], tahoe_single['cwnd'],
            color=TAHOE_COLOR, linewidth=1.1, label='Tahoe', zorder=3)
    ax.plot(reno_single['time'], reno_single['cwnd'],
            color=RENO_COLOR, linewidth=1.1, label='Reno', zorder=3)
    ax.axhline(y=BOTTLENECK_BDP, color=REF_COLOR, linestyle='--',
               linewidth=0.9, alpha=0.6, zorder=1)
    ax.text(0.98, 0.05, f'BDP = {BOTTLENECK_BDP}', transform=ax.transAxes,
            fontsize=7.5, color='#9E9E9E', ha='right', va='bottom', style='italic')
    _style_ax(ax, 'Time (s)', 'cwnd (pkts)', '(a) Congestion Window')
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    _clean_legend(ax)

    # (b) RTT — single run for sharp correlation with cwnd
    ax = axes[0, 1]
    ax.plot(tahoe_single['time'], tahoe_single['rtt'],
            color=TAHOE_COLOR, linewidth=1.1, label='Tahoe', zorder=3)
    ax.plot(reno_single['time'], reno_single['rtt'],
            color=RENO_COLOR, linewidth=1.1, label='Reno', zorder=3)
    ax.axhline(y=BASE_RTT * 1000, color=REF_COLOR, linestyle='--',
               linewidth=0.9, alpha=0.6, zorder=1)
    ax.text(0.98, 0.05, f'Base RTT = {BASE_RTT*1000:.0f} ms', transform=ax.transAxes,
            fontsize=7.5, color='#9E9E9E', ha='right', va='bottom', style='italic')
    _style_ax(ax, 'Time (s)', 'RTT (ms)', '(b) Round-Trip Time')
    ax.set_xlim(left=0)
    _clean_legend(ax)

    # (c) Drop Rate — averaged for stability
    ax = axes[1, 0]
    ax.plot(tahoe_avg['time'], tahoe_avg['drop_rate'],
            color=TAHOE_COLOR, linewidth=1.1, label='Tahoe', zorder=3)
    ax.plot(reno_avg['time'], reno_avg['drop_rate'],
            color=RENO_COLOR, linewidth=1.1, label='Reno', zorder=3)
    _style_ax(ax, 'Time (s)', 'Drop Rate (%)', '(c) Packet Drop Rate')
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    _clean_legend(ax)

    # (d) Throughput — averaged for stability
    ax = axes[1, 1]
    ax.plot(tahoe_avg['time'], tahoe_avg['throughput'],
            color=TAHOE_COLOR, linewidth=1.1, label='Tahoe', zorder=3)
    ax.plot(reno_avg['time'], reno_avg['throughput'],
            color=RENO_COLOR, linewidth=1.1, label='Reno', zorder=3)
    ax.axhline(y=bottleneck_kbps, color=REF_COLOR, linestyle='--',
               linewidth=0.9, alpha=0.6, zorder=1)
    ax.text(0.98, 0.05, f'Capacity = {bottleneck_kbps:.0f} kbps', transform=ax.transAxes,
            fontsize=7.5, color='#9E9E9E', ha='right', va='bottom', style='italic')
    _style_ax(ax, 'Time (s)', 'Throughput (kbps)', '(d) Throughput')
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    _clean_legend(ax)

    plt.tight_layout(pad=1.8, rect=[0, 0, 1, 0.96])
    plt.savefig(os.path.join(output_dir, 'summary_dashboard.png'), dpi=200,
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("  Saved: summary_dashboard.png")


# =============================================================================
# CSV Export
# =============================================================================
def save_csv_files(tahoe_single, reno_single, tahoe_avg, reno_avg,
                   tahoe_stats, reno_stats, output_dir):
    """Save simulation data to CSV files for reproducibility and analysis.

    Creates 5 CSV files in output_dir:
      - cwnd_data.csv        : single-run congestion window (ACK-level)
      - rtt_data.csv         : single-run round-trip time (ACK-level)
      - throughput_data.csv  : 5-run averaged throughput (ACK-level)
      - drop_rate_data.csv   : 5-run averaged packet drop rate (ACK-level)
      - summary_results.csv  : final aggregated statistics table
    """
    csv_dir = os.path.join(output_dir, 'csv')
    os.makedirs(csv_dir, exist_ok=True)

    # ---- 1. Congestion Window (single run) ----
    path = os.path.join(csv_dir, 'cwnd_data.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ACK_Event', 'Tahoe_cwnd_pkts', 'Reno_cwnd_pkts'])
        for i in range(len(tahoe_single['cwnd'])):
            w.writerow([i + 1,
                        round(tahoe_single['cwnd'][i], 4),
                        round(reno_single['cwnd'][i], 4)])
    print(f"  Saved: csv/cwnd_data.csv  ({len(tahoe_single['cwnd'])} rows)")

    # ---- 2. Round-Trip Time (single run) ----
    path = os.path.join(csv_dir, 'rtt_data.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ACK_Event', 'Tahoe_RTT_ms', 'Reno_RTT_ms'])
        for i in range(len(tahoe_single['rtt'])):
            w.writerow([i + 1,
                        round(tahoe_single['rtt'][i], 4),
                        round(reno_single['rtt'][i], 4)])
    print(f"  Saved: csv/rtt_data.csv  ({len(tahoe_single['rtt'])} rows)")

    # ---- 3. Throughput (5-run average) ----
    path = os.path.join(csv_dir, 'throughput_data.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ACK_Event', 'Time_s',
                     'Tahoe_Throughput_kbps', 'Reno_Throughput_kbps'])
        for i in range(len(tahoe_avg['throughput'])):
            w.writerow([i + 1,
                        round(tahoe_avg['time'][i], 6),
                        round(tahoe_avg['throughput'][i], 4),
                        round(reno_avg['throughput'][i], 4)])
    print(f"  Saved: csv/throughput_data.csv  ({len(tahoe_avg['throughput'])} rows)")

    # ---- 4. Drop Rate (5-run average) ----
    path = os.path.join(csv_dir, 'drop_rate_data.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ACK_Event', 'Time_s',
                     'Tahoe_DropRate_pct', 'Reno_DropRate_pct'])
        for i in range(len(tahoe_avg['drop_rate'])):
            w.writerow([i + 1,
                        round(tahoe_avg['time'][i], 6),
                        round(tahoe_avg['drop_rate'][i], 4),
                        round(reno_avg['drop_rate'][i], 4)])
    print(f"  Saved: csv/drop_rate_data.csv  ({len(tahoe_avg['drop_rate'])} rows)")

    # ---- 5. Summary Results ----
    path = os.path.join(csv_dir, 'summary_results.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Metric', 'TCP Tahoe', 'TCP Reno'])
        for key in tahoe_stats:
            if key != 'Algorithm':
                w.writerow([key, tahoe_stats[key], reno_stats[key]])
    print(f"  Saved: csv/summary_results.csv")

    print(f"  All CSV files saved to: {csv_dir}/")


# =============================================================================
# Statistics
# =============================================================================
def compute_stats(data, label):
    """Compute summary statistics."""
    return {
        'Algorithm': label,
        'Avg cwnd (pkts)': f'{np.mean(data["cwnd"]):.2f}',
        'Max cwnd (pkts)': f'{np.max(data["cwnd"]):.1f}',
        'Min cwnd (pkts)': f'{np.min(data["cwnd"]):.1f}',
        'Std cwnd': f'{np.std(data["cwnd"]):.2f}',
        'Avg RTT (ms)': f'{np.mean(data["rtt"]):.1f}',
        'Max RTT (ms)': f'{np.max(data["rtt"]):.1f}',
        'Avg Drop Rate (%)': f'{np.mean(data["drop_rate"]):.2f}',
        'Overall Drop Rate (%)': f'{data["total_dropped"]/max(data["total_sent"],1)*100:.2f}',
        'Avg Throughput (kbps)': f'{np.mean(data["throughput"]):.1f}',
        'Max Throughput (kbps)': f'{np.max(data["throughput"]):.1f}',
        'Total Packets Sent': str(data['total_sent']),
        'Total Packets Dropped': str(data['total_dropped']),
        'Total Packets ACKed': str(data['total_acked']),
        'RTO Timeouts': str(data.get('timeouts', 0)),
    }


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 65)
    print("  TCP Congestion Control Simulation: Tahoe vs Reno")
    print("  (Mininet topology + discrete-event simulation)")
    print("=" * 65)
    print(f"\n  Mininet Topology: {_topo.__class__.__name__}")
    print(f"    Sender->Router:     {_topo.SENDER_ROUTER_BW_Mbps:.1f} Mbps, "
          f"{_topo.SENDER_ROUTER_DELAY_MS:.0f} ms delay")
    print(f"    Router->Receiver:   {_topo.ROUTER_RECEIVER_BW_Mbps:.1f} Mbps, "
          f"{_topo.ROUTER_RECEIVER_DELAY_MS:.0f} ms delay (bottleneck)")
    print(f"    Packet Size:        {PACKET_SIZE} bytes")
    print(f"    Router Queue:       {ROUTER_QUEUE_SIZE} packets")
    print(f"    Base RTT:           {BASE_RTT*1000:.0f} ms")
    print(f"    BDP:                {BOTTLENECK_BDP} packets")
    print(f"    Loss Threshold:     {LOSS_THRESHOLD_CWND} packets")
    print(f"    Min RTO:            {MIN_RTO*1000:.0f} ms")
    print(f"    Total ACK Events:   {TOTAL_ACK_EVENTS}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.abspath(os.path.join(script_dir, '..', 'output'))
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'─'*65}")
    print("  Phase 1: Running TCP Tahoe (5 averaged runs)")
    print(f"{'─'*65}")
    tahoe_data = run_multi_sim(simulate_tahoe, num_runs=5, seed_base=42)

    print(f"\n{'─'*65}")
    print("  Phase 2: Running TCP Reno (5 averaged runs)")
    print(f"{'─'*65}")
    reno_data = run_multi_sim(simulate_reno, num_runs=5, seed_base=42)

    print(f"\n{'─'*65}")
    print("  Phase 3: Generating Comparison Graphs")
    print(f"{'─'*65}")
    tahoe_single = simulate_tahoe(seed=42)
    reno_single = simulate_reno(seed=1042)
    generate_graphs(tahoe_single, reno_single, tahoe_data, reno_data, output_dir)

    print(f"\n{'─'*65}")
    print("  Phase 4: Summary Statistics")
    print(f"{'─'*65}")
    tahoe_stats = compute_stats(tahoe_data, 'TCP Tahoe')
    reno_stats = compute_stats(reno_data, 'TCP Reno')

    print(f"\n  {'Metric':<28} {'Tahoe':>15} {'Reno':>15}")
    print(f"  {'─'*58}")
    for key in tahoe_stats:
        if key != 'Algorithm':
            print(f"  {key:<28} {tahoe_stats[key]:>15} {reno_stats[key]:>15}")

    print(f"\n{'─'*65}")
    print("  Phase 5: Exporting CSV Data Files")
    print(f"{'─'*65}")
    save_csv_files(tahoe_single, reno_single, tahoe_data, reno_data,
                   tahoe_stats, reno_stats, output_dir)

    # Save stats JSON
    stats_output = {
        'tahoe': tahoe_stats,
        'reno': reno_stats,
        'network_params': {
            'topology_class': _topo.__class__.__name__,
            'sender_to_router_bw_mbps': _topo.SENDER_ROUTER_BW_Mbps,
            'router_to_receiver_bw_mbps': _topo.ROUTER_RECEIVER_BW_Mbps,
            'sender_to_router_delay_ms': _topo.SENDER_ROUTER_DELAY_MS,
            'router_to_receiver_delay_ms': _topo.ROUTER_RECEIVER_DELAY_MS,
            'packet_size_bytes': PACKET_SIZE,
            'router_queue_size': ROUTER_QUEUE_SIZE,
            'base_rtt_ms': BASE_RTT * 1000,
            'bdp_packets': BOTTLENECK_BDP,
            'loss_threshold_cwnd': LOSS_THRESHOLD_CWND,
            'min_rto_ms': MIN_RTO * 1000,
            'total_ack_events': TOTAL_ACK_EVENTS,
        }
    }
    stats_path = os.path.join(output_dir, 'simulation_stats.json')
    with open(stats_path, 'w') as f:
        json.dump(stats_output, f, indent=2)
    print(f"\n  Statistics saved to: {stats_path}")
    print(f"\n{'='*65}")
    print(f"  Simulation Complete! Graphs saved to: {output_dir}/")
    print(f"{'='*65}")


if __name__ == '__main__':
    main()