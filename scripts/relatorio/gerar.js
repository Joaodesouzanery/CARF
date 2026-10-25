const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Header, Footer,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType, PageNumber, PageBreak, LevelFormat,
  ExternalHyperlink } = require('docx');

const DIR = process.argv[2] || '.', OUT = process.argv[3] || 'modelo-relatorio-carf.docx';
const d = JSON.parse(fs.readFileSync(DIR + '/dados.json', 'utf8'));
const FONT = 'Arial', NAVY = '1F3864', GRAY = '595959', W = 9638;
const pct = (x, c = 1) => (x * 100).toLocaleString('pt-BR', { minimumFractionDigits: c, maximumFractionDigits: c }) + '%';
const num = (x) => Number(x).toLocaleString('pt-BR');
const RES = { NEGADO: 'Negado', PROVIDO: 'Provido', PROVIDO_PARCIAL: 'Provido em parte', NAO_CONHECIDO: 'Não conhecido',
  ACOLHIDO: 'Embargos acolhidos', REJEITADO: 'Embargos rejeitados', MISTO: 'Misto', OUTRO: 'Outro' };

const run = (t, o = {}) => new TextRun({ text: t, font: FONT, size: 21, ...o });
const ph = (t) => run(t, { highlight: 'yellow' });                // campo a preencher
const p = (children, o = {}) => new Paragraph({ spacing: { after: 120, line: 288 }, ...o,
  children: Array.isArray(children) ? children : [run(children)] });
const dica = (t) => p([run('Instrução ao consultor: ' + t, { italics: true, color: '7F7F7F', size: 18 })], { spacing: { after: 160 } });
const h1 = (t) => new Paragraph({ keepNext: true, heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 140 },
  children: [new TextRun({ text: t, font: FONT, bold: true, size: 30, color: NAVY })],
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 4 } } });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 220, after: 100 },
  children: [new TextRun({ text: t, font: FONT, bold: true, size: 24, color: NAVY })] });
const bullet = (children) => new Paragraph({ numbering: { reference: 'pontos', level: 0 }, spacing: { after: 90, line: 276 },
  children: Array.isArray(children) ? children : [run(children)] });

const borda = { style: BorderStyle.SINGLE, size: 4, color: 'BFBFBF' };
const bordas = { top: borda, bottom: borda, left: borda, right: borda };
function cel(txt, w, o = {}) {
  const kids = (Array.isArray(txt) ? txt : [txt]).map((t) => (typeof t === 'string'
    ? new Paragraph({ alignment: o.align || AlignmentType.LEFT, spacing: { after: 40 }, keepNext: o.keep,
        children: [run(t, { bold: o.bold, color: o.color, size: o.size || 19 })] }) : t));
  return new TableCell({ width: { size: w, type: WidthType.DXA }, borders: bordas, verticalAlign: 'center',
    shading: o.fill ? { fill: o.fill, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 }, children: kids, columnSpan: o.span });
}
function tabela(cols, cab, linhas, o = {}) {
  const head = new TableRow({ tableHeader: true, children: cab.map((c, i) =>
    cel(c, cols[i], { bold: true, fill: NAVY, color: 'FFFFFF', keep: true, align: i ? AlignmentType.CENTER : AlignmentType.LEFT })) });
  const rows = linhas.map((l, r) => new TableRow({ cantSplit: true, children: l.map((c, i) =>
    cel(c, cols[i], { fill: r % 2 ? 'F2F2F2' : undefined, keep: r < linhas.length - 1, align: i && !o.esquerda ? AlignmentType.CENTER : AlignmentType.LEFT })) }));
  return new Table({ width: { size: cols.reduce((a, b) => a + b), type: WidthType.DXA }, columnWidths: cols, rows: [head, ...rows] });
}
const espaco = () => p('', { spacing: { after: 80 } });

// ---------- dados derivados ----------
const a25 = d.ano.find((x) => x.ano === 2025), a18 = d.ano.find((x) => x.ano === 2018);
const q3 = d.q3, q3prov = ((q3.res.PROVIDO || 0) + (q3.res.PROVIDO_PARCIAL || 0)) / q3.n, q3neg = (q3.res.NEGADO || 0) / q3.n;
const e = d.estoque, partEst = e.pis_cofins / e.total_geral;
const melhor = [...d.turma].sort((a, b) => b.prov - a.prov)[0], pior = [...d.turma].sort((a, b) => a.prov - b.prov)[0];

// ---------- capa ----------
const capa = [
  new Paragraph({ spacing: { before: 1800, after: 120 }, children: [run('MODELO DE RELATÓRIO', { bold: true, size: 20, color: GRAY, characterSpacing: 60 })] }),
  new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: 'Boletim de Jurisprudência CARF', font: FONT, bold: true, size: 56, color: NAVY })] }),
  new Paragraph({ spacing: { after: 600 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: NAVY, space: 8 } },
    children: [new TextRun({ text: 'PIS/COFINS: créditos, insumos e tendência de julgamento', font: FONT, size: 28, color: GRAY })] }),
  tabela([2600, 7038], ['Campo', 'Conteúdo'], [
    ['Cliente', [new Paragraph({ children: [ph('[Nome do escritório]')] })]],
    ['Período coberto', [new Paragraph({ children: [ph('[3º trimestre de 2026]')] })]],
    ['Matéria', 'PIS/COFINS (exemplo)'],
    ['Elaborado por', [new Paragraph({ children: [ph('[Nome do consultor / empresa]')] })]],
    ['Data de emissão', [new Paragraph({ children: [ph('[dd/mm/aaaa]')] })]],
    ['Base de dados', `Acórdãos do CARF indexados até 24/10/2026; dados abertos oficiais de Julgamentos (até 2025) e Estoque (${e.ref})`],
  ], { esquerda: true }),
  espaco(),
  p([run('Este modelo usa dados públicos reais do CARF como exemplo. Os campos em ', { size: 18, color: GRAY }),
     ph('amarelo'), run(' são preenchidos a cada edição. Apoio à pesquisa jurídica: não constitui parecer nem previsão de resultado.', { size: 18, color: GRAY })]),
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------- corpo ----------
const resumo = new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: [W], rows: [new TableRow({ children: [new TableCell({
  width: { size: W, type: WidthType.DXA }, borders: { top: { style: BorderStyle.SINGLE, size: 18, color: NAVY }, bottom: borda, left: borda, right: borda },
  shading: { fill: 'EAF0FA', type: ShadingType.CLEAR, color: 'auto' }, margins: { top: 140, bottom: 140, left: 200, right: 200 },
  children: [
    new Paragraph({ spacing: { after: 100 }, children: [run('O que mudou e o que importa', { bold: true, size: 24, color: NAVY })] }),
    bullet([run(`Em 2025 foram julgados ${num(a25.total)} recursos de PIS/COFINS no CARF; `), run(`${pct(a25.prov)} tiveram provimento total ou parcial`, { bold: true }), run(` (em 2018, ${pct(a18.prov)}).`)]),
    bullet([run(`No ${'3º trimestre de 2026'}, o índice registra ${num(q3.n)} acórdãos citando PIS ou COFINS, de ${num(q3.total_periodo)} no total. Pela leitura automática das decisões, ${pct(q3prov, 0)} foram providos (total ou parcial) e ${pct(q3neg, 0)} negados `), run('(indicativo)', { italics: true }), run('.')]),
    bullet([run(`${num(e.pis_cofins)} processos de PIS/COFINS aguardam no CARF (${pct(partEst, 0)} do estoque, ${e.ref}); a mediana de permanência é de ${num(e.mediana_dias)} dias.`)]),
    bullet([run('Ação sugerida: '), ph('[1 a 3 recomendações práticas ao escritório, por exemplo teses a priorizar ou colegiados a observar]')]),
  ] })] })] });

const kpis = new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: [2409, 2409, 2410, 2410], rows: [new TableRow({ children: [
  [num(a25.total), 'recursos julgados\nem PIS/COFINS (2025)'], [pct(a25.prov), 'providos, total ou parcial\n(2025)'],
  [num(e.pis_cofins), `processos em estoque\n(${e.ref})`], [num(e.mediana_dias), 'dias de mediana\nno CARF'] ].map(([v, r], i) => new TableCell({
  width: { size: i < 2 ? 2409 : 2410, type: WidthType.DXA }, borders: bordas, shading: { fill: 'F7F9FC', type: ShadingType.CLEAR, color: 'auto' },
  margins: { top: 140, bottom: 140, left: 100, right: 100 }, children: [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, children: [new TextRun({ text: v, font: FONT, bold: true, size: 40, color: NAVY })] }),
    ...r.split('\n').map((l) => new Paragraph({ alignment: AlignmentType.CENTER, children: [run(l, { size: 17, color: GRAY })] })) ] })) })] });

const img = fs.readFileSync(DIR + '/grafico.png');
const novidades = d.novidades.flatMap((n) => [
  new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: [2400, 7238], rows: [
    new TableRow({ cantSplit: true, children: [cel(n.cit, 2400, { bold: true, fill: 'EAF0FA', keep: true }), cel(`${n.turma} | sessão ${n.data} | resultado: ${RES[n.res] || n.res} (leitura automática)`, 7238, { fill: 'EAF0FA', size: 18, keep: true })] }),
    new TableRow({ cantSplit: true, children: [cel('Ementa (trecho)', 2400, { color: GRAY, size: 18, keep: true }), cel(n.ementa + '…', 7238, { size: 18, keep: true })] }),
    new TableRow({ cantSplit: true, children: [cel('Por que importa', 2400, { color: GRAY, size: 18, keep: true }), cel([new Paragraph({ keepNext: true, children: [ph('[1 a 2 frases: efeito prático para os clientes do escritório]')] })], 7238, { size: 18 })] }),
    new TableRow({ cantSplit: true, children: [cel('Fonte', 2400, { color: GRAY, size: 18 }), cel([new Paragraph({ children: [
      new ExternalHyperlink({ link: n.link, children: [run(`Processo ${n.proc}: PDF do acórdão`, { size: 18, color: '0563C1', underline: {} })] })] })], 7238)] }),
  ] }), espaco()]);

const corpo = [
  h1('1. Resumo executivo'), dica('no máximo uma página; escreva a ação sugerida por último, olhando os números abaixo.'), resumo, espaco(),
  h1('2. Painel de indicadores'), dica('manter sempre os mesmos quatro indicadores para o cliente comparar edição a edição.'), kpis,
  p([run('Fontes: dados abertos oficiais de Julgamentos (2025) e de Estoque (' + e.ref + ').', { size: 17, color: GRAY })], { spacing: { before: 80 } }),
  h1('3. Tendência de julgamento'),
  p(`A taxa de provimento em PIS/COFINS passou de ${pct(a18.prov)} em 2018 para ${pct(a25.prov)} em 2025, enquanto a de negativa caiu de ${pct(a18.neg)} para ${pct(a25.neg)}. Os números abaixo são do resultado oficial publicado pelo CARF.`),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100, after: 100 }, children: [new ImageRun({ type: 'png', data: img, transformation: { width: 600, height: 267 },
    altText: { title: 'Tendência', description: 'Resultado dos recursos de PIS/COFINS por ano', name: 'grafico' } })] }),
  tabela([1400, 1900, 2112, 2113, 2113], ['Ano', 'Recursos julgados', 'Providos (total/parcial)', 'Negados', 'Não conhecidos'],
    d.ano.map((a) => [String(a.ano), num(a.total), pct(a.prov), pct(a.neg), pct(a.nc)])),
  h1('4. Por colegiado'),
  p(`Em 2025, entre os colegiados com ao menos 30 julgamentos em PIS/COFINS, a taxa de provimento variou de ${pct(pior.prov, 0)} (${pior.turma_fmt}) a ${pct(melhor.prov, 0)} (${melhor.turma_fmt}).`, { keepNext: true }),
  tabela([4638, 1400, 1800, 1800], ['Colegiado', 'Recursos', 'Providos (total/parcial)', 'Negados'],
    d.turma.map((t) => [t.turma_fmt, num(t.total), pct(t.prov), pct(t.neg)]), { esquerda: false }),
  p([run('Leitura por colegiado (não por conselheiro): estatística de julgamento coletivo, com amostra mínima de 30 casos.', { size: 17, color: GRAY })], { spacing: { before: 80 } }),
  h1('5. Novidades relevantes do período'), dica('escolha de 3 a 8 acórdãos ligados às teses dos clientes; sempre cite número, turma, data e link.'),
  ...novidades,
  h1('6. Estoque e prazos'),
  p(`Em ${e.ref}, o CARF tinha ${num(e.pis_cofins)} processos de PIS/COFINS em estoque, ${pct(partEst, 0)} de ${num(e.total_geral)}. A mediana de permanência é de ${num(e.mediana_dias)} dias, e 90% dos processos aguardam menos de ${num(e.p90_dias)} dias.`, { keepNext: true }),
  tabela([6238, 3400], ['Fase processual', 'Processos de PIS/COFINS'], Object.entries(e.fases).map(([k, v]) => [k, num(v)]), { esquerda: false }),
  h1('7. Pontos de atenção e recomendações'), dica('é a parte que o cliente paga para ler: seja específico e priorize.'),
  bullet([ph('[Tese em movimento: o que mudou, em qual colegiado, com qual acórdão]')]),
  bullet([ph('[Risco ou oportunidade para casos em andamento dos clientes]')]),
  bullet([ph('[Próximos passos recomendados e prazo]')]),
  h1('8. Metodologia, fontes e limites'),
  bullet('Acórdãos: índice público de jurisprudência do CARF, atualizado até 24/10/2026. Texto anonimizado antes de ser armazenado; relatores e conselheiros (agentes públicos) são preservados.'),
  bullet('Resultado oficial: dado aberto "CARF - Julgamentos de processos", por recurso. É a base das taxas das seções 2, 3 e 4.'),
  bullet('Resultado "leitura automática": classificação por regras sobre o texto da decisão, validada contra o resultado oficial (acurácia geral entre 92,7% e 97,6% em amostras de 2025). É indicativa, sem equivalência com o dado oficial.'),
  bullet(`Estoque: dado aberto "CARF - Estoque de processos", ${e.ref}. Tempo no CARF medido pela data de entrada.`),
  bullet('Limites: a anonimização reduz risco, mas não o elimina; resultados estatísticos descrevem o passado e não preveem o desfecho de um caso concreto.'),
  p([run('Apoio à pesquisa jurídica. Não constitui parecer jurídico nem previsão de resultado. Confira sempre o acórdão de origem.', { italics: true, size: 18, color: GRAY })], { spacing: { before: 200 } }),
];

const doc = new Document({
  creator: 'CARF Intelligence', title: 'Boletim de Jurisprudência CARF (modelo)',
  styles: { default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 30, bold: true, font: FONT, color: NAVY }, paragraph: { outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 24, bold: true, font: FONT, color: NAVY }, paragraph: { outlineLevel: 1 } } ] },
  numbering: { config: [{ reference: 'pontos', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1247, bottom: 1134, left: 1134, right: 1134 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run('Boletim de Jurisprudência CARF | PIS/COFINS', { size: 16, color: '7F7F7F' })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      run('Confidencial | Página ', { size: 16, color: '7F7F7F' }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: '7F7F7F' }),
      run(' de ', { size: 16, color: '7F7F7F' }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: '7F7F7F' })] })] }) },
    children: [...capa, ...corpo] }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log('ok', b.length); });
