"""Preserved V4.4.3 geometry reviewer used for equivalence regression."""
def review_geometry(report):
    """Surface disagreements with an independent strict-extrema interpretation.

    This is a review criterion, not a proof that the upstream interpretation is
    universally wrong. Unreviewed parent structures cannot certify a signal.
    """
    fractals={f['source']:f for f in report['base']['fractals']};issues=[];bad_strokes=set();bad_segments=set()
    for s in report['base']['strokes']:
        reasons=[]
        if s['state']=='confirmed' and s['start'] in fractals and s['end'] in fractals:
            a,z=fractals[s['start']]['merged_index'],fractals[s['end']]['merged_index']
            part=report['base']['merged'][a:z+1]
            expected=(min(x['low'] for x in part),max(x['high'] for x in part))
            actual=(s['start_price'],s['end_price']) if s['direction']=='up' else (s['end_price'],s['start_price'])
            if actual!=expected:reasons.append('standard_interval_extrema_disagreement')
        s['review_issues']=reasons
        if reasons:bad_strokes.add(s['id']);issues.append({'id':s['id'],'kind':'stroke','reasons':reasons})
    for s in report['base']['segments']:
        part=[m for m in report['base']['strokes'] if s['start']<=m['start'] and m['end']<=s['end']]
        reasons=[]
        if s['state']=='confirmed' and part:
            vertices=[m['start_price'] for m in part]+[part[-1]['end_price']]
            actual=(s['start_price'],s['end_price']) if s['direction']=='up' else (s['end_price'],s['start_price'])
            if actual!=(min(vertices),max(vertices)):reasons.append('input_vertex_extrema_disagreement')
            if any(m['id'] in bad_strokes for m in part):reasons.append('contains_stroke_requiring_review')
        s['review_issues']=reasons
        if reasons:bad_segments.add(s['id']);issues.append({'id':s['id'],'kind':'segment','reasons':reasons})
    bad_centers=set()
    for layer in report.get('hierarchy',{}).get('levels',[]):
        bad_children=bad_strokes if layer['rank']==1 else bad_segments
        for center in layer['centers']:
            if any(component in bad_children for component in center.get('components',[])):
                center['review_issues']=['contains_component_requiring_review'];bad_centers.add(center['id'])
            else:center['review_issues']=[]
    for p in report['signals']:
        dependencies=[];start,end=p['terminal_range']
        for s in report['base']['strokes']:
            if s['start']<=end and s['end']>=start and s['id'] in bad_strokes:dependencies.append(s['id'])
        for s in report['base']['segments']:
            if s['start']<=end and s['end']>=start and s['id'] in bad_segments:dependencies.append(s['id'])
        if p.get('center_id') in bad_centers:dependencies.append(p['center_id'])
        if p.get('native_type','').startswith('3') and not p.get('center_id'):
            dependencies.append('native_center_relation_not_uniquely_mapped')
        p['review_dependencies']=dependencies
        if dependencies and p['state']!='invalidated':
            p['state']='needs_review';p['rule_audit']['passed']=False;p['rule_audit']['local_geometry_completed']=False
            p['rule_audit']['missing']=['independent_geometry_review_required']
    report['geometry_review']={'profile':'independent_strict_extrema_review_v1','issues':issues,
                               'stroke_issues':len(bad_strokes),'segment_issues':len(bad_segments),
                               'semantics':'strict-extrema interpretation disagreement; not an automatic original-theory verdict'}
    return report

