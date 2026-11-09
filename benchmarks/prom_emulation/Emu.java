import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * Research emulation of ProM's ActiTraC, reimplemented from reading its source:
 * Heuristics Miner, ICS replay and the two greedy clusterers. It exists to find out
 * which behaviours explain the difference from this package; see run.py and
 * docs/fidelity.md. Flags switch each behaviour off.
 */
public class Emu {

    // ---- ordered int set: same binary search and insert behaviour as HNSubSet.
    static final class S implements Comparable<S> {
        int[] a; int n;
        S() { a = new int[10]; }
        S(S o) { a = o.a.clone(); n = o.n; }
        int get(int i) { return a[i]; }
        int bs(int key) {
            int low = 0, high = n - 1;
            while (low <= high) {
                int mid = (low + high) >> 1, v = a[mid];
                if (v < key) low = mid + 1; else if (v > key) high = mid - 1; else return mid;
            }
            return -(low + 1);
        }
        boolean contains(int v) { return bs(v) >= 0; }
        void add(int v) {
            int p = bs(v);
            if (p < 0) {
                p = -p - 1;
                if (n == a.length) a = Arrays.copyOf(a, n * 2);
                System.arraycopy(a, p, a, p + 1, n - p);
                a[p] = v; n++;
            }
        }
        void remove(int v) {
            int p = bs(v);
            if (p >= 0) { System.arraycopy(a, p + 1, a, p, n - p - 1); n--; }
        }
        void removeAll(S o) { for (int i = 0; i < o.n; i++) remove(o.a[i]); }
        public int compareTo(S o) {
            if (n != o.n) return n < o.n ? -1 : 1;
            for (int i = 0; i < n; i++) if (a[i] != o.a[i]) return a[i] < o.a[i] ? -1 : 1;
            return 0;
        }
        boolean same(S o) { return compareTo(o) == 0; }
    }

    // ---- ordered set of subsets: same behaviour as HNSet, including its binary
    // search over subsets that were mutated after insertion.
    static final class H {
        S[] a; int n;
        H() { a = new S[10]; }
        H(H o) { a = new S[o.a.length]; n = o.n; for (int i = 0; i < n; i++) a[i] = new S(o.a[i]); }
        int bs(S key) {
            int low = 0, high = n - 1;
            while (low <= high) {
                int mid = (low + high) >> 1, c = a[mid].compareTo(key);
                if (c < 0) low = mid + 1; else if (c > 0) high = mid - 1; else return mid;
            }
            return -(low + 1);
        }
        void add(S s) {
            int p = bs(s);
            if (p < 0) {
                p = -p - 1;
                if (n == a.length) a = Arrays.copyOf(a, n * 2);
                System.arraycopy(a, p, a, p + 1, n - p);
                a[p] = s; n++;
            }
        }
        void remove(S s) {
            int p = bs(s);
            if (p >= 0) { System.arraycopy(a, p + 1, a, p, n - p - 1); n--; }
        }
        void removeAll(H o) { for (int i = 0; i < o.n; i++) remove(o.a[i]); }
        static S union(H h) { S u = new S(); for (int i = 0; i < h.n; i++) { S s = h.a[i]; for (int j = 0; j < s.n; j++) u.add(s.a[j]); } return u; }
    }

    static final class Comb {
        S tasks = new S(); int missing;
        Comb copy() { Comb c = new Comb(); c.setTokens(missing); c.tasks = new S(tasks); return c; }
        void setTokens(int m) { missing = m > 0 ? m : 0; }
    }

    // ---- toggles
    static boolean STICKY = true, FLOAT = true, RNG = true, EARLY = true, EXACTSUM = false;

    static final class Settings {
        double dep = 0.9, l1l = 0.9, l2l = 0.9;
        final double rel = 0.05, and = 0.1; final int pos = 1, div = 1;
    }

    static final class Rand {
        final Random r = RNG ? new Random(Long.MAX_VALUE) : null;
        int nextInt(int b) { return r == null ? 0 : r.nextInt(b); }
    }

    // ---- data
    static String[] classNames;   // sorted class identities
    static int[][] V;             // variant traces in global class ids, ordered as GroupedXLog
    static int[] F;               // cases per variant
    static int G;                 // number of classes
    static int[] LABEL;

    // ---- a mined net plus its marking state
    static final class Net {
        int n; int[] glob2loc;
        H[] in, out;
        int[][] outIdx; int[][] mark; int[][][] rel; int[][] inUnion;
        int[] nOut;
        int start, end, tokens;
        double fitness;

        void prepare() {
            outIdx = new int[n][]; mark = new int[n][]; rel = new int[n][n][]; inUnion = new int[n][]; nOut = new int[n];
            for (int t = 0; t < n; t++) {
                H h = out[t]; List<S> distinct = new ArrayList<>(); outIdx[t] = new int[h.n]; nOut[t] = h.n;
                for (int j = 0; j < h.n; j++) {
                    int k = -1;
                    for (int d = 0; d < distinct.size(); d++) if (distinct.get(d).same(h.a[j])) { k = d; break; }
                    if (k < 0) { k = distinct.size(); distinct.add(h.a[j]); }
                    outIdx[t][j] = k;
                }
                mark[t] = new int[distinct.size()];
                for (int k = 0; k < distinct.size(); k++) {
                    S s = distinct.get(k);
                    for (int i = 0; i < s.n; i++) {
                        int x = s.a[i];
                        int[] old = rel[x][t];
                        if (old == null) rel[x][t] = new int[]{k};
                        else { int[] nw = Arrays.copyOf(old, old.length + 1); nw[old.length] = k; rel[x][t] = nw; }
                    }
                }
            }
            for (int t = 0; t < n; t++) { S u = H.union(in[t]); inUnion[t] = Arrays.copyOf(u.a, u.n); }
        }

        void reset() {
            tokens = 1; start = 1; end = 0;
            for (int[] m : mark) Arrays.fill(m, 0);
        }

        S emptyOutputs(int el) {
            S res = new S();
            for (int task : inUnion[el]) {
                int[] ks = rel[el][task];
                if (ks == null) { res.add(task); continue; }
                for (int k : ks) if (mark[task][k] <= 0) { res.add(task); break; }
            }
            return res;
        }

        Comb bestSet(int el, Rand g) {
            Comb b = new Comb(); int miss = 0;
            H inp = in[el];
            if (inp.n == 0) {
                if (start <= 0) miss++;
            } else {
                S none = emptyOutputs(el);
                H copy = new H(inp), tmp = new H();
                for (int i = 0; i < copy.n; i++) {
                    S s = copy.a[i]; s.removeAll(none);
                    if (s.n == 0) miss++; else tmp.add(s);
                }
                if (tmp.n > 0) b = bestCombo(b, tmp, -1, new Comb(), new S(), g);
            }
            b.setTokens(b.missing + miss);
            return b;
        }

        Comb bestCombo(Comb best, H inp, int root, Comb comb, S treated, Rand g) {
            if (best.tasks.n == 0 || best.missing > comb.missing) {
                S noTokens = null;
                if (root != -1) {
                    H marked = new H();
                    for (int i = 0; i < inp.n; i++) if (inp.a[i].contains(root)) marked.add(inp.a[i]);
                    noTokens = H.union(marked);
                    inp.removeAll(marked);
                    comb.tasks.add(root);
                }
                if (inp.n == 0) {
                    best = comb.copy();
                } else {
                    if (root != -1) {
                        H tmp = new H();
                        for (int i = 0; i < inp.n; i++) {
                            S s = inp.a[i]; s.removeAll(noTokens); s.removeAll(treated);
                            if (s.n == 0) comb.setTokens(comb.missing + 1); else tmp.add(s);
                        }
                        inp = tmp;
                    }
                    for (int i = 0; i < inp.n; i++) {
                        S s = inp.a[i];
                        while (s.n > 0) {
                            int task = s.a[g.nextInt(s.n)];
                            best = bestCombo(best, new H(inp), task, comb.copy(), new S(treated), g);
                            treated.add(task);
                            s.remove(task);
                        }
                    }
                }
            }
            return best;
        }

        int fire(int el, Rand g) {
            Comb b = bestSet(el, g);
            if (in[el].n == 0) {
                if (start > 0) { start--; tokens--; }
            } else {
                for (int i = 0; i < b.tasks.n; i++) {
                    int task = b.tasks.a[i]; int[] ks = rel[el][task];
                    if (ks != null) for (int k : ks) if (mark[task][k] > 0) { mark[task][k]--; tokens--; }
                }
            }
            if (nOut[el] == 0) { tokens++; end++; }
            else { tokens += nOut[el]; for (int k : outIdx[el]) mark[el][k]++; }
            return b.missing;
        }

        int rParsed, rMissing, rExtra;

        void replay(int[] trace, Rand g) {
            reset(); rParsed = 0; rMissing = 0;
            for (int ev : trace) {
                int el = glob2loc[ev];
                if (el < 0) { rMissing++; continue; }
                int t = fire(el, g);
                if (t > 0) rMissing += t; else rParsed++;
            }
            rExtra = end > 0 ? tokens - 1 : tokens;
        }

        float traceFitness(int[] trace) {
            replay(trace, new Rand());
            float f = rParsed; f -= rExtra; f -= rMissing; f /= trace.length;
            return f;
        }
    }

    // ---- ImprovedContinuousSemantics over a log given as ordered variant indices.
    // Returns false as soon as a missing token rules out a fitness of 1.
    static boolean fits(Net net, int[] log, int m) {
        Rand g = new Rand();
        double cases = 0, events = 0, parsed = 0, miss = 0, extra = 0, cm = 0, ce = 0;
        for (int q = 0; q < m; q++) {
            int v = log[q]; int[] tr = V[v];
            for (int c = 0; c < F[v]; c++) {
                net.replay(tr, g);
                if (net.rMissing > 0) {
                    if (EARLY) return false;
                    cm++; miss += net.rMissing;
                }
                if (net.rExtra > 0) { ce++; extra += net.rExtra; }
                parsed += net.rParsed; cases++; events += tr.length;
            }
        }
        double f = (parsed - (miss / (cases - cm + 1) + extra / (cases - ce + 1))) / events;
        net.fitness = f;
        return FLOAT ? ((float) f) >= 1.0f : f >= 1.0;
    }

    // ---- ProcessModel: thresholds of the shared settings object stay lowered.
    static Settings settings = new Settings();

    static Settings adapt(int cases) {
        Settings s = STICKY ? settings : new Settings();
        double t = (double) cases / ((double) cases + 1), min = t - 0.01;
        if (t < s.dep) s.dep = min;
        if (t < s.l1l) s.l1l = min;
        if (t < s.l2l) s.l2l = min;
        return s;
    }

    // ---- HeuristicsMinerNoUI.makeBasicRelations without long distance.
    static Net mine(int[] log, int m) {
        int cases = 0;
        for (int q = 0; q < m; q++) cases += F[log[q]];
        Settings st = adapt(cases);
        boolean[] seen = new boolean[G];
        for (int q = 0; q < m; q++) for (int e : V[log[q]]) seen[e] = true;
        int[] g2l = new int[G]; int n = 0;
        for (int i = 0; i < G; i++) g2l[i] = seen[i] ? n++ : -1;
        double[][] d = new double[n][n], d2 = new double[n][n];
        double[] l1 = new double[n], sc = new double[n], ec = new double[n];
        for (int q = 0; q < m; q++) {
            int[] tr = V[log[q]]; int fr = F[log[q]];
            int last = -1, pen = -1;
            for (int ev : tr) {
                int e = g2l[ev];
                if (last != -1) { d[last][e] += fr; if (last == e) l1[e] += fr; }
                if (pen == e) d2[e][last] += fr;
                pen = last; last = e;
            }
            sc[g2l[tr[0]]] += fr; ec[g2l[tr[tr.length - 1]]] += fr;
        }
        boolean[] L1 = new boolean[n]; int[] L2 = new int[n];
        double[] bim = new double[n], bom = new double[n]; int[] bie = new int[n], boe = new int[n];
        S[] inS = new S[n], outS = new S[n];
        double[][] acc = new double[n][n];
        int bestStart = 0, bestEnd = 0;
        for (int i = 0; i < n; i++) {
            L2[i] = -1; bim[i] = -10; bom[i] = -10; bie[i] = -1; boe[i] = -1; inS[i] = new S(); outS[i] = new S();
            double c = l1[i];
            if (c > 0) {
                double dm = c / (c + st.div);
                if (dm >= st.l1l && d[i][i] >= st.pos) { acc[i][i] = dm; L1[i] = true; inS[i].add(i); outS[i].add(i); }
            }
            if (i > 0) {
                if (sc[i] > sc[bestStart]) bestStart = i;
                if (ec[i] > ec[bestEnd]) bestEnd = i;
            }
        }
        for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) {
            double l2m = l2l(i, j, d2, L1, st);
            if (i > j) {
                double sc2 = d2[i][j] + d2[j][i];
                if (l2m >= st.l2l && sc2 >= st.pos) {
                    acc[i][j] = l2m; acc[j][i] = l2m; L2[i] = j; L2[j] = i;
                    inS[i].add(j); outS[i].add(j); inS[j].add(i); outS[j].add(i);
                }
            }
            if (i != j) {
                double dm = (d[i][j] - d[j][i]) / (d[i][j] + d[j][i] + st.div);
                if (dm > bom[i]) { bom[i] = dm; boe[i] = j; }
                if (dm > bim[j]) { bim[j] = dm; bie[j] = i; }
            }
        }
        for (int i = 0; i < n; i++) if (i != bestStart && i != bestEnd) for (int j = 0; j < n; j++) {
            double l2m = l2l(i, j, d2, L1, st);
            if (l2m > bim[i]) {
                acc[i][j] = l2m; acc[j][i] = l2m; L2[i] = j; L2[j] = i;
                inS[i].add(j); outS[i].add(j); inS[j].add(i); outS[j].add(i);
            }
        }
        for (int i = 0; i < n; i++) {
            int j = L2[i];
            if (i != bestStart && !(j > -1 && bim[j] > bim[i])) {
                int b = bie[i]; acc[b][i] = bim[i]; inS[i].add(b); outS[b].add(i);
            }
            if (i != bestEnd && !(j > -1 && bom[j] > bom[i])) {
                int b = boe[i]; acc[i][b] = bom[i]; inS[b].add(i); outS[i].add(b);
            }
        }
        for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) if (acc[i][j] <= 0.0001) {
            double dm = (d[i][j] - d[j][i]) / (d[i][j] + d[j][i] + st.div);
            if (bom[i] - dm <= st.rel && d[i][j] >= st.pos && dm >= st.dep) {
                acc[i][j] = dm; inS[j].add(i); outS[i].add(j);
            }
        }
        Net net = new Net(); net.n = n; net.glob2loc = g2l; net.in = new H[n]; net.out = new H[n];
        for (int i = 0; i < n; i++) {
            net.in[i] = orSets(i, inS[i], d, st, true);
            net.out[i] = orSets(i, outS[i], d, st, false);
        }
        net.prepare();
        return net;
    }

    static double l2l(int i, int j, double[][] d2, boolean[] L1, Settings st) {
        double a = d2[i][j], b = d2[j][i];
        if (!((L1[i] && a >= st.pos) || (L1[j] && b >= st.pos))) { double s = a + b; return s / (s + st.div); }
        return 0.0;
    }

    static double andM(int owner, int old, int nw, double[][] d, Settings st, boolean in) {
        if (owner == nw) return 0.0;
        if (d[old][nw] < st.pos || d[nw][old] < st.pos) return 0.0;
        double den = in ? d[nw][owner] + d[old][owner] + 1 : d[owner][nw] + d[owner][old] + 1;
        return (d[old][nw] + d[nw][old]) / den;
    }

    static boolean welcome(int owner, int nw, S h, double[][] d, Settings st, boolean in) {
        boolean w = true;
        for (int i = 0; i < h.n; i++) if (andM(owner, h.a[i], nw, d, st, in) > st.and) w = false;
        return w;
    }

    static H orSets(int owner, S set, double[][] d, Settings st, boolean in) {
        H h = new H();
        for (int i = 0; i < set.n; i++) {
            int e = set.a[i]; boolean any = false;
            for (int k = 0; k < h.n; k++) {
                S g = h.a[k];
                if (welcome(owner, e, g, d, st, in)) { any = true; g.add(e); }
            }
            if (!any) { S g = new S(); g.add(e); h.add(g); }
        }
        for (int i = 0; i < set.n; i++) {
            int e = set.a[i];
            for (int k = 0; k < h.n; k++) {
                S g = h.a[k];
                if (welcome(owner, e, g, d, st, in)) g.add(e);
            }
        }
        return h;
    }

    // ---- GreedyClusterer
    static long[] greedy(int k, float mcs) {
        settings = new Settings();
        ArrayList<Integer> log = new ArrayList<>();
        long nb = 0;
        for (int i = 0; i < V.length; i++) { log.add(i); nb += F[i]; }
        adapt((int) nb);
        List<Net> models = new ArrayList<>(); List<long[]> sizes = new ArrayList<>();
        int created = 0;
        boolean stop = false;
        int[] buf = new int[V.length];
        while (!stop) {
            long added = 0;
            ArrayList<Integer> good = new ArrayList<>(); good.add(0);
            int cur = 1;
            while (cur < log.size()) {
                good.add(cur);
                int m = 0; for (int gi : good) buf[m++] = log.get(gi);
                Net mod = mine(buf, m);
                if (fits(mod, buf, m)) { added += F[log.get(cur)]; cur++; }
                else {
                    good.remove(good.size() - 1);
                    if ((float) added >= mcs * (float) nb) break;
                    cur++;
                }
            }
            int m = 0; for (int gi : good) buf[m++] = log.get(gi);
            Net model = mine(buf, m);
            long size = 0;
            for (int i = good.size() - 1; i >= 0; i--) { int gi = good.get(i); LABEL[log.get(gi)] = models.size(); size += F[log.get(gi)]; nb -= F[log.get(gi)]; log.remove(gi); }
            cur = 0;
            while (cur < log.size()) {
                int v = log.get(cur);
                if (model.traceFitness(V[v]) == 1.0f) { LABEL[v] = models.size(); size += F[v]; nb -= F[v]; log.remove(cur); cur--; }
                cur++;
            }
            models.add(model); sizes.add(new long[]{size});
            created++;
            if (k <= created) stop = true;
            if (log.size() == 0) break;
        }
        return residual(log, models, sizes);
    }

    static long[] residual(List<Integer> left, List<Net> models, List<long[]> sizes) {
        for (int v : left) {
            float best = Float.NEGATIVE_INFINITY; int bi = -1;
            for (int c = 0; c < models.size(); c++) {
                float f = models.get(c).traceFitness(V[v]);
                if (f > best) { best = f; bi = c; }
            }
            sizes.get(bi)[0] += F[v]; LABEL[v] = bi;
        }
        long[] out = new long[sizes.size()];
        for (int i = 0; i < out.length; i++) out[i] = sizes.get(i)[0];
        return out;
    }

    // ---- GreedyDistanceClusterer. D is the matrix behind getDistance.
    interface Dist { float get(int a, int b); }

    static long[] greedyDistance(int k, float mcs, float greed, Dist dist) {
        settings = new Settings();
        int n = V.length;
        long total = 0; for (int f : F) total += f;
        adapt((int) total);
        boolean[] dpi = new boolean[n]; Arrays.fill(dpi, true);
        List<Net> models = new ArrayList<>(); List<long[]> sizes = new ArrayList<>();
        int nb = 0; boolean stop = n == 0;
        int[] buf = new int[n + 1];
        while (!stop) {
            nb++;
            boolean[] d2 = dpi.clone();
            int inDpi = 0; for (int i = 0; i < n; i++) if (dpi[i]) inDpi += F[i];
            ArrayList<Integer> good = new ArrayList<>();
            for (int i = 0; i < n; i++) if (d2[i]) { good.add(i); d2[i] = false; break; }
            // The model's log lists the newest dpi first (ProcessModel.add).
            ArrayDeque<Integer> order = new ArrayDeque<>(); order.addFirst(good.get(0));
            buf[0] = good.get(0);
            Net model = mine(buf, 1);
            boolean cs = !fits(model, buf, 1);
            int size = F[good.get(0)];
            while (!cs) {
                int index = -1;
                int minFreq = 0, left = 0;
                for (int j = 0; j < n; j++) if (d2[j]) left++;
                left *= greed;
                for (int j = 0; j < n; j++) {
                    if (!d2[j]) continue;
                    left--;
                    if (left <= 0) { minFreq = F[j]; break; }
                }
                int minD = Integer.MAX_VALUE;
                double minExact = Double.POSITIVE_INFINITY;
                for (int i = 0; i < n; i++) {
                    if (!d2[i]) continue;
                    if (F[i] < minFreq) break;
                    if (EXACTSUM) {
                        double distance = 0;
                        for (int g : good) distance += dist.get(g, i);
                        if (distance < minExact) { index = i; minExact = distance; }
                    } else {
                        int distance = 0;
                        for (int g : good) distance += dist.get(g, i);
                        if (distance < minD) { index = i; minD = distance; }
                    }
                }
                if (index == -1) break;
                int m = 0; buf[m++] = index; for (int v : order) buf[m++] = v;
                Net nm = mine(buf, m);
                if (fits(nm, buf, m)) {
                    size += F[index]; good.add(index); order.addFirst(index); d2[index] = false; model = nm;
                } else {
                    int minimal = (int) (inDpi * mcs);
                    if (size >= minimal) cs = true; else d2[index] = false;
                }
            }
            for (int g : good) { dpi[g] = false; LABEL[g] = models.size(); }
            long s = size;
            for (int i = 0; i < n; i++) {
                if (!dpi[i]) continue;
                if (model.traceFitness(V[i]) == 1.0f) { s += F[i]; dpi[i] = false; LABEL[i] = models.size(); }
            }
            models.add(model); sizes.add(new long[]{s});
            if (k <= nb) stop = true;
            boolean any = false; for (boolean b : dpi) if (b) { any = true; break; }
            if (!any) stop = true;
        }
        List<Integer> left = new ArrayList<>();
        for (int i = 0; i < n; i++) if (dpi[i]) left.add(i);
        return residual(left, models, sizes);
    }

    // ---- input: raw traces of names and lifecycles, grouped as GroupedXLog does.
    static List<String[][]> variantsRaw = new ArrayList<>();

    static void read(String path) throws IOException {
        Map<String, Integer> groups = new HashMap<>();
        List<String[][]> raw = new ArrayList<>(); List<int[]> cnt = new ArrayList<>();
        TreeSet<String> classes = new TreeSet<>();
        for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
            if (line.isEmpty()) continue;
            Integer g = groups.get(line);
            if (g == null) {
                String[] ev = line.split("\t");
                String[][] t = new String[ev.length][];
                for (int i = 0; i < ev.length; i++) { t[i] = ev[i].split("\u001f", -1); classes.add(t[i][0] + "+" + t[i][1]); }
                g = raw.size(); groups.put(line, g); raw.add(t); cnt.add(new int[]{0});
            }
            cnt.get(g)[0]++;
        }
        Integer[] idx = new Integer[raw.size()];
        for (int i = 0; i < idx.length; i++) idx[i] = i;
        Arrays.sort(idx, (a, b) -> cnt.get(b)[0] - cnt.get(a)[0]); // stable, as Collections.sort
        classNames = classes.toArray(new String[0]); G = classNames.length;
        Map<String, Integer> id = new HashMap<>();
        for (int i = 0; i < G; i++) id.put(classNames[i], i);
        V = new int[idx.length][]; F = new int[idx.length];
        for (int i = 0; i < idx.length; i++) {
            String[][] t = raw.get(idx[i]); F[i] = cnt.get(idx[i])[0]; V[i] = new int[t.length];
            variantsRaw.add(t);
            for (int j = 0; j < t.length; j++) V[i][j] = id.get(t[j][0] + "+" + t[j][1]);
        }
    }

    public static void main(String[] args) throws Exception {
        // args: file k mode(freq|dist) flags. See FLAGS in run.py.
        read(args[0]);
        int k = Integer.parseInt(args[1]); String mode = args[2];
        String lookup = "bug";
        for (int i = 3; i < args.length; i++) {
            String a = args[i];
            if (a.equals("nosticky")) STICKY = false;
            else if (a.equals("nofloat")) FLOAT = false;
            else if (a.equals("norng")) RNG = false;
            else if (a.equals("full")) EARLY = false;
            else if (a.equals("exactsum")) EXACTSUM = true;
            else if (a.startsWith("lookup=")) lookup = a.substring(7);
            else if (a.equals("sorted")) Mra.SORTED = true;
            else if (a.startsWith("seed=")) Mra.SEED = Integer.parseInt(a.substring(5));
            else if (a.equals("allstreams")) Mra.ALLSTREAMS = true;
            else if (a.equals("truelen")) Mra.TRUELEN = true;
            else if (a.equals("nofilter")) Mra.NOFILTER = true;
        }
        LABEL = new int[V.length];
        long t0 = System.currentTimeMillis();
        long[] res;
        if (mode.equals("freq")) res = greedy(k, 0.25f);
        else {
            final float[][] rows = new float[V.length][];
            Mra.build(variantsRaw, F);
            java.util.function.IntFunction<float[]> rowf = a -> {
                if (rows[a] == null) rows[a] = Mra.row(a);
                return rows[a];
            };
            Dist dist;
            if (lookup.equals("ok")) dist = (a, b) -> a == b ? 0f : rowf.apply(a)[b];
            else dist = (a, b) -> { if (a == b) return 0f; int lo = Math.min(a, b), hi = Math.max(a, b); return rowf.apply(lo)[hi - lo]; };
            res = greedyDistance(k, 0.25f, 0.25f, dist);
        }
        for (int i = 3; i < args.length; i++) if (args[i].startsWith("labels=")) try (PrintWriter w = new PrintWriter(args[i].substring(7), "UTF-8")) {
            for (int v = 0; v < V.length; v++) {
                StringBuilder b = new StringBuilder();
                for (String[] ev : variantsRaw.get(v)) b.append(b.length() > 0 ? "\t" : "").append(ev[0]).append('\u001f').append(ev[1]);
                w.println(LABEL[v] + "\t" + b);
            }
        }
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < res.length; i++) sb.append(i > 0 ? "," : "").append(res[i]);
        System.out.println(sb.append("] ").append((System.currentTimeMillis() - t0) / 1000).append("s"));
    }
}
